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
from sender.legacy.resend_file_util import (
    extract_retry_count,
    increment_retry_name,
    mark_as_fail,
)

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

        # Phase 0 NEW keys (stored for future phases; do not change behavior here)
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

        self.resend_quota_mb = self.sender_config_model.resend_quota_mb
        self.fs_free_min_mb = self.sender_config_model.fs_free_min_mb

        # ---- Phase 0: shared HTTP client & last success time ----
        self._client: httpx.AsyncClient | None = None
        self.last_post_ok_at: datetime | None = None

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
        Start background tasks (Phase 0 keeps original behavior):
          - Create shared AsyncClient
          - _resend_failed_files(): run once at start (legacy behavior)
          - _warmup_send_once(): wait first snapshot → send immediately
          - _scheduler_loop(): aligned periodic sending
        """
        # Phase 0: create shared client
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=5.0)
            logger.info("[Sender] Shared HTTP client created (timeout=5.0s)")

        # Keep existing boot-time resend
        await self._resend_failed_files()
        asyncio.create_task(self._warmup_send_once())
        asyncio.create_task(self._scheduler_loop())

    async def stop(self):
        """Phase 0: graceful close shared client (optional if service never stops)."""
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

                    # Phase 1: persist each item first
                    fp = await self._persist_item_json({"DeviceID": it["DeviceID"], "Data": it["Data"]})
                    outbox_files.append(fp)

                all_data.extend(converted)
                sent_candidates_sampling_ts[dev_id] = snap_ts

        # Treat GW heartbeat also as an item to be resent
        gw_item = self._make_gw_heartbeat(label_now)
        all_data.append(gw_item)
        fp_gw = await self._persist_item_json(gw_item)
        outbox_files.append(fp_gw)

        payload = self._wrap_items_as_payload(all_data, label_now)

        ok = await self._post_with_retry(payload)
        if ok and sent_candidates_sampling_ts:
            for dev_id in sent_candidates_sampling_ts:
                self.__last_label_ts_by_device[dev_id] = label_now
            self.__last_sent_ts_by_device.update(sent_candidates_sampling_ts)
            await self._prune_buckets()

        # Phase 1: delete persisted files only after success
        if ok and outbox_files:
            await self._delete_files(outbox_files)

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

        # ensure client exists (defensive for tests)
        client = self._client or httpx.AsyncClient(timeout=5.0)

        try:
            for i in range(self.__attempt_count):
                try:
                    resp = await client.post(self.ima_url, json=payload)
                    if self._is_ok(resp):
                        logger.info(f"[POST] ok: {resp.status_code}")
                        # Phase 0: update last success time
                        self.last_post_ok_at = datetime.now(self._tz)
                        return True
                    else:
                        logger.warning(f"[POST] not ok (status={resp.status_code}) preview={resp.text[:200]!r}")
                except Exception as e:
                    logger.warning(f"[POST] attempt {i+1} failed: {e}")

                if i < len(backoffs):
                    await asyncio.sleep(backoffs[i])
        finally:
            # if we created a temp client (no shared), close it
            if self._client is None:
                try:
                    await client.aclose()
                except Exception:
                    pass

        await self._enforce_resend_storage_budget()
        return False

    async def _resend_failed_files(self) -> None:
        """
        Phase 1: Support two file formats
        A) Old: full PushIMAData packet (with FUNC/version/...)
        B) New: single item ({'DeviceID':..., 'Data': {...}})
           -> Automatically wrapped into a PushIMAData packet before sending
        """
        try:
            file_list = sorted(
                [f for f in os.listdir(self.resend_dir) if f.endswith(".json") or re.search(r"\.retry\d+\.json$", f)]
            )
        except FileNotFoundError:
            os.makedirs(self.resend_dir, exist_ok=True)
            file_list = []

        client = self._client or httpx.AsyncClient(timeout=5.0)

        try:
            for file_name in file_list:
                file_path = os.path.join(self.resend_dir, file_name)
                retry_count = extract_retry_count(file_name)

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
                        payload = self._wrap_items_as_payload([json_obj], datetime.now(self._tz))
                    else:
                        payload = raw

                    headers = None
                    if isinstance(payload, str):
                        headers = {"Content-Type": "application/json"}

                    if isinstance(payload, dict):
                        resp = await client.post(self.ima_url, json=payload)
                    else:
                        resp = await client.post(self.ima_url, data=payload, headers=headers)

                    logger.info(f"[RESEND] {file_name}, resp: {resp.status_code} {resp.text[:120]!r}")

                    if self._is_ok(resp):
                        os.remove(file_path)
                        self.last_post_ok_at = datetime.now(self._tz)
                        logger.info(f"[RESEND] success, deleted: {file_name}")
                    else:
                        if retry_count + 1 >= self.__max_retry:
                            mark_as_fail(file_path)
                            logger.warning(f"[RESEND] marked .fail: {file_name}")
                        else:
                            new_name = increment_retry_name(file_name)
                            os.rename(file_path, os.path.join(self.resend_dir, new_name))
                            logger.info(f"[RESEND] retry {retry_count + 1}, renamed to: {new_name}")
                except Exception as e:
                    logger.warning(f"[RESEND] failed for {file_name}: {e}")

            await self._enforce_resend_storage_budget()
        finally:
            if self._client is None:
                try:
                    await client.aclose()
                except Exception:
                    pass

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

    async def _persist_failed_json(self, obj: dict) -> None:
        now = datetime.now(self._tz)
        base = now.strftime("%Y%m%d%H%M%S")
        ms = f"{int(now.microsecond/1000):03d}"
        suffix = os.urandom(2).hex()  # 4 hex chars
        filename = os.path.join(self.resend_dir, f"resend_{base}_{ms}_{suffix}.json")
        try:
            async with aiofiles.open(filename, "w", encoding="utf-8") as f:
                await f.write(json.dumps(obj, ensure_ascii=False))
            logger.warning(f"[RESEND] persisted: {filename}")
        except Exception as e:
            logger.error(f"[RESEND] persist failed: {e}")

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

            # Phase 0 keeps legacy behavior (resend here)
            await self._resend_failed_files()
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

                    # Phase 1: persist each item first
                    fp = await self._persist_item_json({"DeviceID": it["DeviceID"], "Data": it["Data"]})
                    outbox_files.append(fp)

                all_items.extend(converted)
                sent_candidates_ts[dev_id] = snap_ts

        # Treat GW heartbeat also as an item to be resent
        gw_item = self._make_gw_heartbeat(label_time)
        all_items.append(gw_item)
        fp_gw = await self._persist_item_json(gw_item)
        outbox_files.append(fp_gw)

        payload = self._wrap_items_as_payload(all_items, label_time)

        ok = await self._post_with_retry(payload)
        if ok and sent_candidates_ts:
            for dev_id in list(sent_candidates_ts):
                self.__last_label_ts_by_device[dev_id] = label_time
            self.__last_sent_ts_by_device.update(sent_candidates_ts)
            await self._prune_buckets()

        # Phase 1: delete persisted files only after success
        if ok and outbox_files:
            await self._delete_files(outbox_files)

    def _dir_size_mb(self, path: str) -> float:
        total = 0
        for root, _, files in os.walk(path):
            for fn in files:
                fp = os.path.join(root, fn)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
        return total / (1024 * 1024)

    def _fs_free_mb(self, path: str) -> float:
        st = os.statvfs(path)
        return (st.f_bavail * st.f_frsize) / (1024 * 1024)

    async def _enforce_resend_storage_budget(self) -> None:
        try:
            over_quota = self._dir_size_mb(self.resend_dir) > self.resend_quota_mb
            low_free = self._fs_free_mb(self.resend_dir) < self.fs_free_min_mb
            if not (over_quota or low_free):
                return

            files = []
            now_ts = datetime.now(self._tz).timestamp()
            for fn in os.listdir(self.resend_dir):
                if not (fn.endswith(".json") or re.search(r"\.retry\d+\.json$", fn) or fn.endswith(".fail")):
                    continue
                fp = os.path.join(self.resend_dir, fn)
                try:
                    age = now_ts - os.path.getmtime(fp)
                except OSError:
                    continue
                files.append((age, fn))

            files.sort(reverse=True)
            deleted = 0
            protect_sec = float(self.sender_config_model.resend_protect_recent_sec)
            batch = int(self.sender_config_model.resend_cleanup_batch)

            def eligible(age):
                return age >= protect_sec

            for age, fn in list(files):
                if deleted >= batch:
                    break
                if not eligible(age):
                    continue
                if fn.endswith(".fail"):
                    continue
                try:
                    os.remove(os.path.join(self.resend_dir, fn))
                    deleted += 1
                except OSError:
                    pass

            if deleted < batch:
                for age, fn in list(files):
                    if deleted >= batch:
                        break
                    if not eligible(age):
                        continue
                    if not fn.endswith(".fail"):
                        continue
                    try:
                        os.remove(os.path.join(self.resend_dir, fn))
                        deleted += 1
                    except OSError:
                        pass

            logger.warning(
                f"[RESEND] cleanup deleted={deleted}, dir_mb={self._dir_size_mb(self.resend_dir):.1f}, free_mb={self._fs_free_mb(self.resend_dir):.1f}"
            )
        except Exception as e:
            logger.error(f"[RESEND] cleanup error: {e}")

    def _make_gw_heartbeat(self, at: datetime) -> dict:
        return {
            "DeviceID": f"{self.gateway_id}_000GW",  # TODO: GW ID need to modify by config on future
            "Data": {"HB": 1, "report_ts": at.isoformat()},
        }

    # ---------- Phase 1 helpers: per-item persist / wrap / delete ----------

    async def _persist_item_json(self, item: dict) -> str:
        """
        Persist a SINGLE Data item (with DeviceID/Data fields) to outbox.
        Return the absolute file path.
        """
        now = datetime.now(self._tz)
        base = now.strftime("%Y%m%d%H%M%S")
        ms = f"{int(now.microsecond/1000):03d}"
        suffix = os.urandom(2).hex()  # 4 hex chars
        fp = os.path.join(self.resend_dir, f"resend_{base}_{ms}_{suffix}.json")
        try:
            async with aiofiles.open(fp, "w", encoding="utf-8") as f:
                await f.write(json.dumps(item, ensure_ascii=False))
            logger.info(f"[OUTBOX] persisted item: {os.path.basename(fp)}")
        except Exception as e:
            logger.error(f"[OUTBOX] persist item failed: {e}")
        return fp

    def _wrap_items_as_payload(self, items: list[dict], ts: datetime) -> dict:
        """Wrap a list of item dicts into a PushIMAData payload."""
        return {
            "FUNC": "PushIMAData",
            "version": "6.0",
            "GatewayID": self.gateway_id,
            "Timestamp": ts.strftime("%Y%m%d%H%M%S"),
            "Data": items,
        }

    async def _delete_files(self, files: list[str]) -> None:
        deleted = 0
        for fp in files:
            try:
                os.remove(fp)
                deleted += 1
            except Exception:
                pass
        if deleted:
            logger.info(f"[OUTBOX] deleted {deleted} sent item file(s)")
