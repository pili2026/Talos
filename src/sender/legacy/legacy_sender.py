import asyncio
import json
import logging
import os
import re
import socket
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import aiofiles
import httpx

from device_manager import AsyncDeviceManager
from model.enum.equipment_enum import EquipmentType
from schema.sender_schema import SenderSchema
from sender.legacy.legacy_format_adapter import convert_snapshot_to_legacy_payload
from sender.outbox_store import OutboxStore
from sender.transport import ResendTransport
from util.system_info.system_info_collector import SystemInfoCollector
from util.time_util import TIMEZONE_INFO

logger = logging.getLogger("LegacySender")


# TODO: Need to Refactor
class LegacySenderAdapter:

    def __init__(self, sender_config_schema: SenderSchema, device_manager: AsyncDeviceManager, series_number: int):
        self.sender_config_model = sender_config_schema
        self.gateway_id = self._resolve_gateway_id(self.sender_config_model.gateway_id)
        self.resend_dir = self.sender_config_model.resend_dir
        self.ima_url = self.sender_config_model.cloud.ima_url

        self.send_interval_sec = float(self.sender_config_model.send_interval_sec)
        self.anchor_offset_sec = float(self.sender_config_model.anchor_offset_sec)
        self.tick_grace_sec = float(self.sender_config_model.tick_grace_sec)
        self.fresh_window_sec = float(self.sender_config_model.fresh_window_sec)
        self.last_known_ttl_sec = float(self.sender_config_model.last_known_ttl_sec or 0.0)

        self.fail_resend_enabled = bool(self.sender_config_model.fail_resend_enabled)
        self.fail_resend_interval_sec = int(self.sender_config_model.fail_resend_interval_sec)
        self.fail_resend_batch = int(self.sender_config_model.fail_resend_batch)
        self.last_post_ok_within_sec = float(self.sender_config_model.last_post_ok_within_sec)
        self.resend_start_delay_sec = int(self.sender_config_model.resend_start_delay_sec)

        self.device_manager = device_manager
        os.makedirs(self.resend_dir, exist_ok=True)

        self.__attempt_count = int(self.sender_config_model.attempt_count)
        self.__max_retry = int(self.sender_config_model.max_retry)

        # window → { device_id → snapshot }; in-memory cache only
        self._latest_per_window: dict[datetime, dict[str, dict]] = defaultdict(dict)
        self._lock = asyncio.Lock()
        self._epoch = datetime(1970, 1, 1, tzinfo=TIMEZONE_INFO)

        # ---- Warm-up state ----
        self._first_snapshot_event = asyncio.Event()
        self._first_send_done = False

        # ---- De-dup tracker ----
        self.__last_sent_ts_by_device: dict[str, datetime] = {}
        self.__last_label_ts_by_device: dict[str, datetime] = {}

        # ---- Storage limits (delegate to store) ----
        self.resend_quota_mb = self.sender_config_model.resend_quota_mb
        self.fs_free_min_mb = self.sender_config_model.fs_free_min_mb

        # ---- Shared HTTP client & last success time ----
        self._client: httpx.AsyncClient | None = None
        self._transport: ResendTransport | None = None
        self.last_post_ok_at: datetime | None = None

        # ---- Background worker state ----
        self._resend_task: asyncio.Task | None = None
        self._resend_wakeup: asyncio.Event = asyncio.Event()
        self._stopping: bool = False

        # ---- Outbox store ----
        self._store = OutboxStore(
            dirpath=self.resend_dir,
            tz=TIMEZONE_INFO,
            gateway_id=self.gateway_id,
            resend_quota_mb=self.resend_quota_mb,
            fs_free_min_mb=self.fs_free_min_mb,
            protect_recent_sec=self.sender_config_model.resend_protect_recent_sec,
            cleanup_batch=self.sender_config_model.resend_cleanup_batch,
            cleanup_enabled=self.sender_config_model.resend_cleanup_enabled,
        )

        self.series_number = series_number
        self.resend_anchor_offset_sec = int(sender_config_schema.resend_anchor_offset_sec)

        try:
            self._system_info = SystemInfoCollector()
            logger.info("[LegacySender] System info collector initialized")

            self._system_info.increment_reboot_count()
        except Exception as e:
            logger.error(f"[LegacySender] Failed to initialize SystemInfoCollector: {e}")
            raise

    # -------------------------
    # Public API
    # -------------------------
    async def handle_snapshot(self, snapshot_map: dict) -> None:
        """
        On receiving a snapshot, place it into the bucket of its window
        (within the same window keep only the last one per device),
        and trigger warm-up once the first snapshot arrives.
        """
        device_id = snapshot_map.get("device_id")
        sampling_ts: datetime | None = snapshot_map.get("sampling_ts")

        if not device_id or not sampling_ts:
            logger.warning(f"[LegacySender] Missing device_id or sampling_ts in snapshot: {snapshot_map}")
            return

        # Ensure tz-aware (normalize to Asia/Taipei)
        if sampling_ts.tzinfo is None:
            sampling_ts = sampling_ts.replace(tzinfo=TIMEZONE_INFO)
        else:
            sampling_ts = sampling_ts.astimezone(TIMEZONE_INFO)

        wstart = LegacySenderAdapter._window_start(sampling_ts, int(self.send_interval_sec), tz=TIMEZONE_INFO)
        async with self._lock:
            self._latest_per_window[wstart][device_id] = {**snapshot_map, "sampling_ts": sampling_ts}

        if not self._first_snapshot_event.is_set():
            self._first_snapshot_event.set()

    async def start(self):
        """
        Start background tasks:
          - Create shared AsyncClient + Transport
          - _warmup_send_once(): wait first snapshot → send immediately
          - _scheduler_loop(): aligned periodic sending
          - _resend_worker_loop(): background resend
        """
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=5.0)
            logger.info("[Sender] Shared HTTP client created (timeout=5.0s)")

        if self._transport is None:
            self._transport = ResendTransport(self.ima_url, self._client, self._is_ok)

        asyncio.create_task(self._warmup_send_once())
        asyncio.create_task(self._scheduler_loop())

        # Start background resend worker (optional by config)
        if self.fail_resend_enabled:
            asyncio.create_task(self._delayed_resend_start())
            logger.info(
                f"[ResendWorker] scheduled to start after {self.resend_start_delay_sec}s "
                f"(interval={self.fail_resend_interval_sec}s, batch={self.fail_resend_batch}, "
                f"health_window={self.last_post_ok_within_sec}s)"
            )

    async def stop(self):
        """Graceful shutdown: stop worker first, then close HTTP client."""
        try:
            self._stopping = True
            self._resend_wakeup.set()
            if self._resend_task is not None:
                self._resend_task.cancel()
                try:
                    await self._resend_task
                except asyncio.CancelledError:
                    pass
        except Exception as e:
            logger.warning(f"[Sender] Error stopping resend worker: {e}")

        # ---- Stop client ----
        try:
            if self._client is not None:
                await self._client.aclose()
                logger.info("[Sender] Shared HTTP client closed")
        except Exception as e:
            logger.warning(f"[Sender] Error closing HTTP client: {e}")

    # -------------------------
    # Internal
    # -------------------------

    async def _warmup_send_once(self, timeout_sec: int = 15, debounce_s: int = 1) -> None:
        try:
            await asyncio.wait_for(self._first_snapshot_event.wait(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            logger.debug("Warm-up: no snapshot within timeout; skip immediate send.")
            return

        if debounce_s > 0:
            await asyncio.sleep(debounce_s)

        latest_by_device = await self._collect_latest_by_device_unlocked()

        all_data: list[dict] = []
        sent_candidates_sampling_ts: dict[str, datetime] = {}
        label_now = datetime.now(TIMEZONE_INFO)

        # --- List of files persisted in this round (only deleted after success) ---
        outbox_files: list[str] = []

        for dev_id, snap in latest_by_device.items():
            last_label = self.__last_label_ts_by_device.get(dev_id, self._epoch)
            if label_now <= last_label:
                continue

            snap_ts: datetime = snap["sampling_ts"]
            age_sec = (label_now - snap_ts).total_seconds()
            is_stale = 1 if age_sec > self.fresh_window_sec else 0

            last_ts = self.__last_sent_ts_by_device.get(dev_id, self._epoch)
            if snap_ts <= last_ts:
                continue

            converted = convert_snapshot_to_legacy_payload(
                gateway_id=self.gateway_id,
                snapshot=snap,
                device_manager=self.device_manager,
            )
            if converted:
                age_ms = int(age_sec * 1000)
                for it in converted:
                    it.setdefault("Data", {})
                    it["Data"]["sampling_ts"] = snap_ts.isoformat()
                    it["Data"]["report_ts"] = label_now.isoformat()
                    it["Data"]["sample_age_ms"] = age_ms
                    if is_stale:
                        it["Data"]["is_stale"] = 1
                        it["Data"]["stale_age_ms"] = age_ms

                    # persist each item first → OutboxStore
                    fp = await self._store.persist_item({"DeviceID": it["DeviceID"], "Data": it["Data"]})
                    outbox_files.append(fp)

                all_data.extend(converted)
                sent_candidates_sampling_ts[dev_id] = snap_ts

        # Treat GW heartbeat also as an item to be resent
        gw_item = await self._make_gw_heartbeat(label_now)
        all_data.append(gw_item)
        fp_gw = await self._store.persist_item(gw_item)
        outbox_files.append(fp_gw)

        payload = self._store.wrap_items_as_payload(all_data, label_now)
        logger.info(f"Warm-up: {payload}")

        ok = await self._post_with_retry(payload)
        if ok and sent_candidates_sampling_ts:
            for dev_id in sent_candidates_sampling_ts:
                self.__last_label_ts_by_device[dev_id] = label_now
            self.__last_sent_ts_by_device.update(sent_candidates_sampling_ts)
            await self._prune_buckets()

        # delete persisted files only after success
        if ok and outbox_files:
            for fp in outbox_files:
                self._store.delete(fp)

        self._first_send_done = True

    # -------------------------
    # Helpers
    # -------------------------
    async def _collect_latest_by_device_unlocked(self) -> dict[str, dict]:
        """
        Compress all buckets → obtain a single "current latest" snapshot per device.
        """
        async with self._lock:
            latest_by_device: dict[str, dict] = {}
            for bucket in self._latest_per_window.values():
                for dev_id, snap in bucket.items():
                    prev = latest_by_device.get(dev_id)
                    if (not prev) or (snap["sampling_ts"] > prev["sampling_ts"]):
                        latest_by_device[dev_id] = snap
        return latest_by_device

    async def _prune_buckets(self) -> None:
        """
        Remove snapshots that were already sent or are older,
        to prevent buckets from growing indefinitely.
        """
        async with self._lock:
            for wstart in list(self._latest_per_window.keys()):
                bucket = self._latest_per_window[wstart]
                for dev_id in list(bucket.keys()):
                    snap_ts = bucket[dev_id]["sampling_ts"]
                    last_ts = self.__last_sent_ts_by_device.get(dev_id, self._epoch)
                    if snap_ts <= last_ts:
                        bucket.pop(dev_id, None)
                if not bucket:
                    self._latest_per_window.pop(wstart, None)

    async def _post_with_retry(self, payload: dict) -> bool:
        payload = self._normalize_missing_deep(payload)
        backoffs = [1, 2][: max(self.__attempt_count - 1, 0)]  # 1s, 2s...

        temp_client = None
        transport = self._transport
        if transport is None:
            temp_client = httpx.AsyncClient(timeout=5.0)
            transport = ResendTransport(self.ima_url, temp_client, self._is_ok)

        try:
            for i in range(self.__attempt_count):
                try:
                    ok, status, text = await transport.send(payload)
                    if ok:
                        logger.info(f"[POST][Payload]: {payload}")
                        logger.info(f"[POST] ok: {status}")
                        # update last success time & wake worker to clear backlog
                        self.last_post_ok_at = datetime.now(TIMEZONE_INFO)
                        self._resend_wakeup.set()
                        return True
                    else:
                        logger.warning(f"[POST] not ok (status={status}) preview={text[:200]!r}")
                except Exception as e:
                    logger.warning(f"[POST] attempt {i+1} failed: {e}")

                if i < len(backoffs):
                    await asyncio.sleep(backoffs[i])
        finally:
            if temp_client is not None:
                try:
                    await temp_client.aclose()
                except Exception:
                    pass

        self._store.enforce_budget()
        return False

    @staticmethod
    def _window_start(ts: datetime, interval_sec: int, tz: ZoneInfo = TIMEZONE_INFO) -> datetime:
        """Align `sampling_ts` to the start of its tumbling window (for internal cache indexing only; does not affect sending)."""
        timestamp_tz = ts.astimezone(tz).replace(microsecond=0)
        interval = int(interval_sec)
        second: int = (timestamp_tz.second // interval) * interval
        return timestamp_tz.replace(second=second)

    @staticmethod
    def _resolve_gateway_id(config_gateway_id: str) -> str:
        """
        Logic for selecting gateway_id:
          1. If hostname is exactly 11 characters:
             - If it equals the default '99999999999' → use config_gid[:11]
             - Otherwise → use hostname
          2. In all other cases → use config_gid[:11]
        """
        hostname: str = socket.gethostname()

        if len(hostname) == 11:
            if hostname == "99999999999":
                gateway_id = config_gateway_id[:11]
                logger.info(f"[GatewayID] Using config gateway_id={gateway_id} (hostname is default {hostname})")
                return gateway_id

            logger.info(f"[GatewayID] Using hostname gateway_id={hostname}")
            return hostname

        gateway_id: str = config_gateway_id[:11]
        logger.info(f"[GatewayID] Using config gateway_id={gateway_id} (hostname not 11 chars)")
        return gateway_id

    @staticmethod
    def _normalize_missing_value(v):
        """Normalize -1.0 / -1 into int(-1); leave other values unchanged."""
        if isinstance(v, (int, float)) and v == -1:
            return -1
        return v

    @staticmethod
    def _normalize_missing_deep(obj):
        """Recursively convert all -1.0 values in a payload back to -1 (supports nested dict/list)."""
        if isinstance(obj, dict):
            return {
                k: LegacySenderAdapter._normalize_missing_deep(LegacySenderAdapter._normalize_missing_value(v))
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [LegacySenderAdapter._normalize_missing_deep(x) for x in obj]
        return LegacySenderAdapter._normalize_missing_value(obj)

    @staticmethod
    def _is_ok(resp: httpx.Response) -> bool:
        return (resp is not None) and (resp.status_code == 200) and ("00000" in (resp.text or ""))

    async def _scheduler_loop(self):
        logger.info(
            f"Scheduler: anchor={self.anchor_offset_sec}s, interval={self.send_interval_sec}s, "
            f"fail_resend_enabled={self.fail_resend_enabled}, fail_resend_interval_sec={self.fail_resend_interval_sec}, "
            f"fail_resend_batch={self.fail_resend_batch}, last_post_ok_within_sec={self.last_post_ok_within_sec}"
        )
        next_label = self._compute_next_label_time(datetime.now(TIMEZONE_INFO))

        while True:
            now = datetime.now(TIMEZONE_INFO)
            wait_sec = (next_label - now).total_seconds()
            if wait_sec > 0:
                await asyncio.sleep(wait_sec)

            if self.tick_grace_sec > 0:
                await asyncio.sleep(self.tick_grace_sec)

            await self._send_at_label_time(next_label)

            next_label = next_label + timedelta(seconds=self.send_interval_sec)

    def _compute_next_label_time(self, now: datetime) -> datetime:
        base_datatime = now.replace(microsecond=0)
        anchor = int(self.anchor_offset_sec)
        candidate = base_datatime.replace(second=anchor)
        interval = float(self.send_interval_sec)

        while candidate <= now:
            candidate += timedelta(seconds=interval)
        return candidate

    async def _send_at_label_time(self, label_time: datetime) -> None:
        latest_by_device = await self._collect_latest_by_device_unlocked()

        all_items: list[dict] = []
        sent_candidates_ts: dict[str, datetime] = {}
        visible_deadline = label_time + timedelta(seconds=self.tick_grace_sec)

        # --- List of files persisted in this round (only deleted after success) ---
        outbox_files: list[str] = []

        for dev_id, snap in latest_by_device.items():
            snap_ts: datetime = snap["sampling_ts"]
            if snap_ts > visible_deadline:
                continue

            age_sec = (label_time - snap_ts).total_seconds()
            is_stale = 1 if age_sec > self.fresh_window_sec else 0

            last_label = self.__last_label_ts_by_device.get(dev_id, self._epoch)
            if label_time <= last_label:
                continue

            converted = convert_snapshot_to_legacy_payload(
                gateway_id=self.gateway_id,
                snapshot=snap,
                device_manager=self.device_manager,
            )
            if converted:
                age_ms = int(age_sec * 1000)
                for it in converted:
                    it.setdefault("Data", {})
                    it["Data"]["sampling_ts"] = snap_ts.isoformat()
                    it["Data"]["report_ts"] = label_time.isoformat()
                    it["Data"]["sample_age_ms"] = age_ms
                    if is_stale:
                        it["Data"]["is_stale"] = 1
                        it["Data"]["stale_age_ms"] = age_ms

                    # persist each item first → OutboxStore
                    fp = await self._store.persist_item({"DeviceID": it["DeviceID"], "Data": it["Data"]})
                    outbox_files.append(fp)

                all_items.extend(converted)
                sent_candidates_ts[dev_id] = snap_ts

        # Treat GW heartbeat also as an item to be resent
        gw_item = await self._make_gw_heartbeat(label_time)
        all_items.append(gw_item)
        fp_gw = await self._store.persist_item(gw_item)
        outbox_files.append(fp_gw)

        payload = self._store.wrap_items_as_payload(all_items, label_time)
        logger.debug(f"Scheduled send:  {payload}")

        ok = await self._post_with_retry(payload)
        if ok and sent_candidates_ts:
            for dev_id in list(sent_candidates_ts):
                self.__last_label_ts_by_device[dev_id] = label_time
            self.__last_sent_ts_by_device.update(sent_candidates_ts)
            await self._prune_buckets()

        # delete persisted files only after success
        if ok and outbox_files:
            for fp in outbox_files:
                self._store.delete(fp)

    async def _make_gw_heartbeat(self, at: datetime) -> dict:
        cpu_temp_task = asyncio.create_task(self._system_info.get_cpu_temperature())
        ssh_port_task = asyncio.create_task(self._system_info.get_ssh_port())

        cpu_temp = await cpu_temp_task
        ssh_port = await ssh_port_task

        return {
            "DeviceID": f"{self.gateway_id}_{self.series_number}00{EquipmentType.GW}",  # TODO: GW ID need to modify by config on future
            "Data": {
                "HB": 1,
                "report_ts": at.isoformat(),
                "SSHPort": ssh_port,
                "WebBulbOffset": cpu_temp,
                "Status": self._system_info.get_reboot_count(),
            },
        }

    # ---------- Background resend worker ----------

    async def _resend_worker_loop(self) -> None:
        """
        Background resend loop with time alignment.

        Features:
        - Each execution is aligned to `resend_anchor_offset_sec`
        - Can be woken up early by `_resend_wakeup` (used to quickly drain backlog after a success)
        - Health gate protection (only runs if there has been a recent successful upload)
        """
        try:
            while not self._stopping:
                # Compute the next aligned run time
                now = datetime.now(TIMEZONE_INFO)
                next_run = self._compute_next_resend_time(now)
                wait_sec = (next_run - now).total_seconds()

                logger.debug(f"[ResendWorker] next run at {next_run.strftime('%H:%M:%S')}, " f"waiting {wait_sec:.1f}s")

                # Wait until the next run time (or get woken up earlier)
                try:
                    await asyncio.wait_for(self._resend_wakeup.wait(), timeout=wait_sec)
                    logger.debug("[ResendWorker] woken up early by success signal")
                except asyncio.TimeoutError:
                    pass  # Normal timeout, reached scheduled run
                finally:
                    self._resend_wakeup.clear()

                if self._stopping:
                    break

                # === Health Gate Check ===
                now = datetime.now(TIMEZONE_INFO)
                if self.last_post_ok_within_sec > 0:
                    if self.last_post_ok_at is None:
                        logger.info("[ResendWorker] skip: no successful POST yet")
                        continue

                    elapsed_time = (now - self.last_post_ok_at).total_seconds()
                    if elapsed_time > self.last_post_ok_within_sec:
                        logger.info(
                            f"[ResendWorker] skip: no recent success within "
                            f"{self.last_post_ok_within_sec}s "
                            f"(last_ok={self.last_post_ok_at.strftime('%H:%M:%S')}, "
                            f"elapsed={elapsed_time:.1f}s)"
                        )
                        continue

                # === Execute Resend Batch ===
                try:
                    processed, success = await self._resend_process_batch(self.fail_resend_batch)

                    if processed == 0:
                        logger.debug("[ResendWorker] no files to process")
                        continue

                    logger.info(f"[ResendWorker] processed {processed} files, " f"succeeded {success}")

                    # If there were successes, wake up early for the next round (to drain backlog faster)
                    if success > 0:
                        self._resend_wakeup.set()

                except Exception as e:
                    logger.warning(f"[ResendWorker] batch error: {e}")

        except asyncio.CancelledError:
            logger.info("[ResendWorker] cancelled")
        except Exception as e:
            logger.error(f"[ResendWorker] crashed: {e}", exc_info=True)

    def _parse_iso_timestamp(self, timestamp_str: str | None) -> datetime | None:
        if not timestamp_str:
            return None
        try:
            dt: datetime = datetime.fromisoformat(timestamp_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TIMEZONE_INFO)
            else:
                dt = dt.astimezone(TIMEZONE_INFO)
            return dt
        except Exception:
            return None

    def _ts_from_filename(self, filename: str) -> datetime | None:
        # Support resend_YYYYmmddHHMMSS_ms_xxxx(.retryN)?.json
        match = re.match(r"resend_(\d{14})_", filename)
        if not match:
            return None
        try:
            base_datetime = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
            return base_datetime.replace(tzinfo=TIMEZONE_INFO)
        except Exception:
            return None

    async def _resend_process_batch(self, batch: int) -> tuple[int, int]:
        """
        Pick up to `batch` files.
        - Full packets are sent as-is (their own Timestamp).
        - Single-item files are grouped by report_ts (fallback: filename ts -> now),
        and each group is sent ONCE as a merged PushIMAData payload using that ts.
        Returns: (total files processed, total files successfully deleted)
        """
        files = self._store.pick_batch(batch, min_age_sec=0.0)
        if not files:
            return 0, 0

        # Prepare transport (use existing client if available)
        temp_client: httpx.AsyncClient | None = None
        transport = self._transport
        if transport is None:
            temp_client = httpx.AsyncClient(timeout=5.0)
            transport = ResendTransport(self.ima_url, temp_client, self._is_ok)

        processed = 0
        deleted_total = 0

        # Stage 1: read & bucketize
        full_packets: list[tuple[str, dict]] = []  # [(file_path, packet_json)]
        item_groups: dict[str, dict] = {}  # ts_key -> { "ts": datetime, "items": [dict], "paths": [str] }

        for file_path in files:
            file_name = os.path.basename(file_path)
            try:
                async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                    raw = await f.read()
            except FileNotFoundError:
                logger.info(f"[ResendWorker] skipped, already gone: {file_name}")
                processed += 1
                continue
            except Exception as e:
                logger.warning(f"[ResendWorker] read failed for {file_name}: {e}")
                # Even if the file cannot be loaded, you still need to retry/fail to avoid getting stuck.
                _, failed = self._store.retry_or_fail(file_path, max_retry=self.__max_retry)
                if failed:
                    logger.warning(f"[ResendWorker] marked .fail: {file_name}")
                processed += 1
                continue

            json_obj = None
            try:
                json_obj = json.loads(raw)
            except Exception:
                # Not a valid JSON, treated as raw (using now instead of ts)
                json_obj = None

            if isinstance(json_obj, dict) and "FUNC" in json_obj:
                # Complete packet: sent independently
                full_packets.append((file_path, json_obj))
            elif isinstance(json_obj, dict) and "DeviceID" in json_obj:
                # Single item: grouped by report_ts
                report_timestamp: str = (json_obj.get("Data") or {}).get("report_ts")
                ts_dt = (
                    self._parse_iso_timestamp(report_timestamp)
                    or self._ts_from_filename(file_name)
                    or datetime.now(TIMEZONE_INFO)
                )
                ts_key = ts_dt.strftime(
                    "%Y%m%d%H%M%S"
                )  # Use second-level time as the key to make the outer timestamp consistent
                g = item_groups.setdefault(ts_key, {"ts": ts_dt, "items": [], "paths": []})
                g["items"].append(json_obj)
                g["paths"].append(file_path)
            else:
                # Unable to determine the structure, treat it as a separate raw packet and use the file name time/now as the Timestamp
                ts_dt = self._ts_from_filename(file_name) or datetime.now(TIMEZONE_INFO)
                ts_key = f"RAW-{ts_dt.strftime('%Y%m%d%H%M%S')}#{file_name}"
                item_groups.setdefault(ts_key, {"ts": ts_dt, "items": [], "paths": []})
                # Wrap it into a single item of Data using raw (keep it as is)
                item_groups[ts_key]["items"].append(json_obj if isinstance(json_obj, dict) else {"_raw": raw})
                item_groups[ts_key]["paths"].append(file_path)

            processed += 1

        # Stage 2: send full packets one-by-one
        for file_path, packet in full_packets:
            file_name = os.path.basename(file_path)
            try:
                ok, status, text = await transport.send(packet)
                logger.info(f"[ResendWorker] (packet) {file_name}, resp: {status} {text[:120]!r}")
                if ok:
                    self._store.delete(file_path)
                    self.last_post_ok_at = datetime.now(TIMEZONE_INFO)
                    deleted_total += 1
                    logger.info(f"[ResendWorker] success, deleted: {file_name}")
                else:
                    _, failed = self._store.retry_or_fail(file_path, max_retry=self.__max_retry)
                    if failed:
                        logger.warning(f"[ResendWorker] marked .fail: {file_name}")
            except Exception as e:
                logger.warning(f"[ResendWorker] failed (packet) for {file_name}: {e}")
                _, failed = self._store.retry_or_fail(file_path, max_retry=self.__max_retry)
                if failed:
                    logger.warning(f"[ResendWorker] marked .fail: {file_name}")

        # Stage 3: send grouped single-items (one request per Timestamp)
        # Send in order of ts to ensure FIFO
        for ts_key, group in sorted(item_groups.items(), key=lambda kv: kv[1]["ts"]):
            ts_dt = group["ts"]
            items = []
            # Filter out the previously inserted RAW styles and only accept legal items
            for it in group["items"]:
                if isinstance(it, dict) and "DeviceID" in it:
                    items.append(it)
                else:
                    # If necessary, you can also wrap RAW into a special DeviceID here; this version will skip this.
                    pass

            if not items:
                continue

            payload = self._store.wrap_items_as_payload(items, ts_dt)
            logger.info(f"[ResendWorker] {payload}")
            file_paths = group["paths"]

            try:
                ok, status, text = await transport.send(payload)
                logger.info(f"[ResendWorker] (group ts={ts_key}) resp: {status} {text[:120]!r}")
                if ok:
                    for p in file_paths:
                        self._store.delete(p)
                        deleted_total += 1
                    self.last_post_ok_at = datetime.now(TIMEZONE_INFO)
                    logger.info(f"[ResendWorker] success, deleted group of {len(file_paths)} file(s) for ts={ts_key}")
                else:
                    # When a failure occurs, each file in the group must advance once retry/fail
                    for p in file_paths:
                        _, failed = self._store.retry_or_fail(p, max_retry=self.__max_retry)
                        if failed:
                            logger.warning(f"[ResendWorker] marked .fail: {os.path.basename(p)}")
            except Exception as e:
                logger.warning(f"[ResendWorker] failed (group ts={ts_key}): {e}")
                for p in file_paths:
                    _, failed = self._store.retry_or_fail(p, max_retry=self.__max_retry)
                    if failed:
                        logger.warning(f"[ResendWorker] marked .fail: {os.path.basename(p)}")

        # Cleanup & return
        if temp_client is not None:
            try:
                await temp_client.aclose()
            except Exception:
                pass

        self._store.enforce_budget()
        return processed, deleted_total

    async def _delayed_resend_start(self):
        """
        Delayed start for Resend Worker, aligned to the configured anchor offset.

        Flow:
        1. Compute the earliest allowed start time = now + resend_start_delay_sec
        2. Find the first aligned point after that earliest time
        3. Wait until the aligned point
        4. Start the worker loop
        """
        now = datetime.now(TIMEZONE_INFO)

        # Compute the earliest allowed start time
        min_start_time = now + timedelta(seconds=self.resend_start_delay_sec)

        # Compute the next aligned time
        next_aligned = self._compute_next_resend_time(min_start_time)

        wait_sec = (next_aligned - now).total_seconds()

        logger.info(
            f"[ResendWorker] scheduled start at {next_aligned.strftime('%Y-%m-%d %H:%M:%S')} "
            f"(anchor={self.resend_anchor_offset_sec}s, "
            f"interval={self.fail_resend_interval_sec}s, "
            f"min_delay={self.resend_start_delay_sec}s, "
            f"waiting {wait_sec:.1f}s)"
        )

        await asyncio.sleep(wait_sec)

        logger.info(f"[ResendWorker] starting now at {datetime.now(TIMEZONE_INFO).strftime('%H:%M:%S')}")
        self._resend_task = asyncio.create_task(self._resend_worker_loop())

    def _compute_next_resend_time(self, after: datetime) -> datetime:
        """
        Compute the next time aligned to resend_anchor_offset_sec.

        Args:
            after: The first aligned point strictly after this timestamp

        Returns:
            Aligned datetime (tz-aware)

        Examples:
            >>> # resend_anchor_offset_sec = 5, fail_resend_interval_sec = 120
            >>> # after = 2025-01-01 12:02:30
            >>> result = _compute_next_resend_time(after)
            >>> # result = 2025-01-01 12:03:05

            >>> # after = 2025-01-01 12:03:10
            >>> result = _compute_next_resend_time(after)
            >>> # result = 2025-01-01 12:05:05
        """
        interval = self.fail_resend_interval_sec
        anchor = self.resend_anchor_offset_sec

        # Compute relative to epoch (ensures consistent timezone)
        epoch = datetime(1970, 1, 1, tzinfo=TIMEZONE_INFO)
        after_tz = after.astimezone(TIMEZONE_INFO) if after.tzinfo else after.replace(tzinfo=TIMEZONE_INFO)

        # Calculate elapsed seconds since epoch
        elapsed_sec = int((after_tz - epoch).total_seconds())

        # Determine the current cycle (starting from 0)
        # Example: elapsed=245, anchor=5, interval=120
        #   -> cycle = (245 - 5) // 120 = 240 // 120 = 2
        cycle = (elapsed_sec - anchor) // interval

        # Compute the next aligned point (cycle + 1)
        next_aligned_sec = (cycle + 1) * interval + anchor
        next_aligned = epoch + timedelta(seconds=next_aligned_sec)

        # Ensure result is strictly later than `after` (handle edge cases)
        while next_aligned <= after_tz:
            next_aligned += timedelta(seconds=interval)

        return next_aligned
