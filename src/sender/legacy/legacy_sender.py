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
from model.sender_model import SenderModel
from sender.legacy.legacy_format_adapter import convert_snapshot_to_legacy_payload
from sender.outbox_store import OutboxStore
from sender.transport import ResendTransport

logger = logging.getLogger("LegacySender")


# TODO: Need to Refactor
class LegacySenderAdapter:

    def __init__(self, sender_config_model: SenderModel, device_manager: AsyncDeviceManager):
        self.sender_config_model = sender_config_model
        self.gateway_id = self._resolve_gateway_id(self.sender_config_model.gateway_id)
        self.resend_dir = self.sender_config_model.resend_dir
        self.ima_url = self.sender_config_model.cloud.ima_url

        self.send_interval_sec = float(self.sender_config_model.send_interval_sec)
        self.anchor_offset_sec = float(self.sender_config_model.anchor_offset_sec)
        self.tick_grace_sec = float(self.sender_config_model.tick_grace_sec)
        self.fresh_window_sec = float(self.sender_config_model.fresh_window_sec)
        self.last_known_ttl_sec = float(self.sender_config_model.last_known_ttl_sec or 0.0)

        # Phase 0/2 keys
        self.fail_resend_enabled = bool(self.sender_config_model.fail_resend_enabled)
        self.fail_resend_interval_sec = int(self.sender_config_model.fail_resend_interval_sec)
        self.fail_resend_batch = int(self.sender_config_model.fail_resend_batch)
        self.last_post_ok_within_sec = float(self.sender_config_model.last_post_ok_within_sec)

        self.device_manager = device_manager
        os.makedirs(self.resend_dir, exist_ok=True)

        self.__attempt_count = int(self.sender_config_model.attempt_count)
        self.__max_retry = int(self.sender_config_model.max_retry)

        # window → { device_id → snapshot }; in-memory cache only
        self._latest_per_window: dict[datetime, dict[str, dict]] = defaultdict(dict)
        self._lock = asyncio.Lock()
        self._tz = ZoneInfo("Asia/Taipei")
        self._epoch = datetime(1970, 1, 1, tzinfo=self._tz)

        # ---- Warm-up state ----
        self._first_snapshot_event = asyncio.Event()
        self._first_send_done = False

        # ---- De-dup tracker ----
        self.__last_sent_ts_by_device: dict[str, datetime] = {}
        self.__last_label_ts_by_device: dict[str, datetime] = {}

        # ---- Storage limits (delegate to store) ----
        self.resend_quota_mb = self.sender_config_model.resend_quota_mb
        self.fs_free_min_mb = self.sender_config_model.fs_free_min_mb

        # ---- Phase 0: shared HTTP client & last success time ----
        self._client: httpx.AsyncClient | None = None
        self._transport: ResendTransport | None = None
        self.last_post_ok_at: datetime | None = None

        # ---- Phase 2: background worker state ----
        self._resend_task: asyncio.Task | None = None
        self._resend_wakeup: asyncio.Event = asyncio.Event()
        self._stopping: bool = False

        # ---- Outbox store ----
        self._store = OutboxStore(
            dirpath=self.resend_dir,
            tz=self._tz,
            gateway_id=self.gateway_id,
            resend_quota_mb=self.resend_quota_mb,
            fs_free_min_mb=self.fs_free_min_mb,
            protect_recent_sec=self.sender_config_model.resend_protect_recent_sec,
            cleanup_batch=self.sender_config_model.resend_cleanup_batch,
            cleanup_enabled=self.sender_config_model.resend_cleanup_enabled,
        )

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
            sampling_ts = sampling_ts.replace(tzinfo=self._tz)
        else:
            sampling_ts = sampling_ts.astimezone(self._tz)

        wstart = LegacySenderAdapter._window_start(sampling_ts, int(self.send_interval_sec), tz="Asia/Taipei")
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
          - (Phase 2) _resend_worker_loop(): background resend
        """
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=5.0)
            logger.info("[Sender] Shared HTTP client created (timeout=5.0s)")

        if self._transport is None:
            self._transport = ResendTransport(self.ima_url, self._client, self._is_ok)

        asyncio.create_task(self._warmup_send_once())
        asyncio.create_task(self._scheduler_loop())

        # Phase 2: start background resend worker (optional by config)
        if self.fail_resend_enabled:
            self._resend_task = asyncio.create_task(self._resend_worker_loop())
            logger.info(
                f"[ResendWorker] started: interval={self.fail_resend_interval_sec}s, "
                f"batch={self.fail_resend_batch}, health_window={self.last_post_ok_within_sec}s"
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
            logger.info("Warm-up: no snapshot within timeout; skip immediate send.")
            return

        if debounce_s > 0:
            await asyncio.sleep(debounce_s)

        latest_by_device = await self._collect_latest_by_device_unlocked()

        all_data: list[dict] = []
        sent_candidates_sampling_ts: dict[str, datetime] = {}
        label_now = datetime.now(self._tz)

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

                    # Phase 1: persist each item first → OutboxStore
                    fp = await self._store.persist_item({"DeviceID": it["DeviceID"], "Data": it["Data"]})
                    outbox_files.append(fp)

                all_data.extend(converted)
                sent_candidates_sampling_ts[dev_id] = snap_ts

        # Treat GW heartbeat also as an item to be resent
        gw_item = self._make_gw_heartbeat(label_now)
        all_data.append(gw_item)
        fp_gw = await self._store.persist_item(gw_item)
        outbox_files.append(fp_gw)

        payload = self._store.wrap_items_as_payload(all_data, label_now)

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
                        logger.info(f"[POST] ok: {status}")
                        # update last success time & wake worker to clear backlog
                        self.last_post_ok_at = datetime.now(self._tz)
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
    def _window_start(ts: datetime, interval_sec: int, tz: str = "Asia/Taipei") -> datetime:
        """Align `sampling_ts` to the start of its tumbling window (for internal cache indexing only; does not affect sending)."""
        ts_tz = ts.astimezone(ZoneInfo(tz)).replace(microsecond=0)
        ival = int(interval_sec)
        sec = (ts_tz.second // ival) * ival
        return ts_tz.replace(second=sec)

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
        next_label = self._compute_next_label_time(datetime.now(self._tz))

        while True:
            now = datetime.now(self._tz)
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

                    # Phase 1: persist each item first → OutboxStore
                    fp = await self._store.persist_item({"DeviceID": it["DeviceID"], "Data": it["Data"]})
                    outbox_files.append(fp)

                all_items.extend(converted)
                sent_candidates_ts[dev_id] = snap_ts

        # Treat GW heartbeat also as an item to be resent
        gw_item = self._make_gw_heartbeat(label_time)
        all_items.append(gw_item)
        fp_gw = await self._store.persist_item(gw_item)
        outbox_files.append(fp_gw)

        payload = self._store.wrap_items_as_payload(all_items, label_time)

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

    def _make_gw_heartbeat(self, at: datetime) -> dict:
        return {
            "DeviceID": f"{self.gateway_id}_000GW",  # TODO: GW ID need to modify by config on future
            "Data": {"HB": 1, "report_ts": at.isoformat()},
        }

    # ---------- Phase 2: background resend worker ----------

    async def _resend_worker_loop(self) -> None:
        """
        Background resend loop:
          - Health threshold: only run if now - last_post_ok_at <= last_post_ok_within_sec
          - Each round processes at most fail_resend_batch files (FIFO: oldest first)
          - Interval: fail_resend_interval_sec, but can be woken up immediately by _resend_wakeup
        """
        try:
            while not self._stopping:
                try:
                    await asyncio.wait_for(self._resend_wakeup.wait(), timeout=self.fail_resend_interval_sec)
                except asyncio.TimeoutError:
                    pass  # Normal timeout, continue execution as usual
                finally:
                    self._resend_wakeup.clear()

                if self._stopping:
                    break

                # Health threshold: only clear the outbox if there was a recent successful upload
                now = datetime.now(self._tz)
                if (
                    self.last_post_ok_at is None
                    or (
                        self.last_post_ok_at
                        and (now - self.last_post_ok_at).total_seconds() > self.last_post_ok_within_sec
                    )
                ) and self.last_post_ok_within_sec > 0:
                    logger.info(
                        "[ResendWorker] skip: no recent success within %ss (last_ok=%s)",
                        self.last_post_ok_within_sec,
                        self.last_post_ok_at.isoformat() if self.last_post_ok_at else "None",
                    )
                    continue

                try:
                    processed, success = await self._resend_process_batch(self.fail_resend_batch)
                    if processed == 0:
                        continue
                    if success > 0:
                        self._resend_wakeup.set()
                except Exception as e:
                    logger.warning(f"[ResendWorker] batch error: {e}")
        except asyncio.CancelledError:
            logger.info("[ResendWorker] cancelled")
        except Exception as e:
            logger.error(f"[ResendWorker] crashed: {e}")

    async def _resend_process_batch(self, batch: int) -> tuple[int, int]:
        """
        Scan the outbox and pick up to `batch` files for processing:
        1) First, pick *.retryN.json (previously failed) → ordered by oldest mtime (FIFO)
        2) Then, pick *.json (fresh files)              → ordered by oldest mtime (FIFO)
        Send them one by one; return (total processed, successfully deleted).
        """
        files = self._store.pick_batch(batch, min_age_sec=0.0)
        if not files:
            return 0, 0

        temp_client: httpx.AsyncClient | None = None
        transport = self._transport
        if transport is None:
            temp_client = httpx.AsyncClient(timeout=5.0)
            transport = ResendTransport(self.ima_url, temp_client, self._is_ok)

        processed = 0
        success = 0

        try:
            for file_path in files:
                file_name = os.path.basename(file_path)

                try:
                    async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                        raw = await f.read()

                    json_obj = None
                    try:
                        json_obj = json.loads(raw)
                    except Exception:
                        pass

                    if isinstance(json_obj, dict) and "FUNC" in json_obj:
                        payload = json_obj
                    elif isinstance(json_obj, dict) and "DeviceID" in json_obj:
                        payload = self._store.wrap_items_as_payload([json_obj], datetime.now(self._tz))
                    else:
                        payload = raw

                    ok, status, text = await transport.send(payload)  # type: ignore[arg-type]
                    logger.info(f"[ResendWorker] {file_name}, resp: {status} {text[:120]!r}")

                    if ok:
                        self._store.delete(file_path)
                        self.last_post_ok_at = datetime.now(self._tz)
                        success += 1
                        logger.info(f"[ResendWorker] success, deleted: {file_name}")
                    else:
                        new_path, failed = self._store.retry_or_fail(file_path, max_retry=self.__max_retry)
                        if failed:
                            logger.warning(f"[ResendWorker] marked .fail: {file_name}")
                        elif new_path:
                            # 取新的 retry 次數展示
                            try:
                                m = re.search(r"\.retry(\d+)\.json$", os.path.basename(new_path))
                                retryN = m.group(1) if m else "?"
                            except Exception:
                                retryN = "?"
                            logger.info(f"[ResendWorker] retry {retryN}, renamed: {os.path.basename(new_path)}")

                except Exception as e:
                    logger.warning(f"[ResendWorker] failed for {file_name}: {e}")
                    new_path, failed = self._store.retry_or_fail(file_path, max_retry=self.__max_retry)
                    if failed:
                        logger.warning(f"[ResendWorker] marked .fail: {file_name}")
                    elif new_path:
                        try:
                            m = re.search(r"\.retry(\d+)\.json$", os.path.basename(new_path))
                            retryN = m.group(1) if m else "?"
                        except Exception:
                            retryN = "?"
                        logger.info(f"[ResendWorker] retry {retryN}, renamed: {os.path.basename(new_path)}")
                finally:
                    processed += 1
        finally:
            if temp_client is not None:
                try:
                    await temp_client.aclose()
                except Exception:
                    pass

            self._store.enforce_budget()

        return processed, success
