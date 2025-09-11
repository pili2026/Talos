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
        self.heartbeat_on_empty = bool(self.sender_config_model.heartbeat_on_empty)
        self.last_known_ttl_sec = float(self.sender_config_model.last_known_ttl_sec or 0.0)

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
        Start two background tasks:
          1) _resend_failed_files: resent fail message
          2) _warmup_send_once: wait for the first snapshot → send immediately (unaligned)
          3) _scheduler_loop:
        """
        await self._resend_failed_files()
        asyncio.create_task(self._warmup_send_once())
        asyncio.create_task(self._scheduler_loop())

    # -------------------------
    # Internal
    # -------------------------
    async def _warmup_send_once(self, timeout_sec: int = 15, debounce_s: int = 1) -> None:
        """
        Warm-up logic:
          - Wait up to `timeout_sec` for the first snapshot
          - Debounce for `debounce_s` seconds if configured
          - Send once immediately using "now" as the label timestamp
        """
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

        for dev_id, snap in latest_by_device.items():
            # 以 "now" 為 label，避免重複送同一 label_time
            last_label = self.__last_label_ts_by_device.get(dev_id, self._epoch)
            if label_now <= last_label:
                continue

            snap_ts: datetime = snap["sampling_ts"]
            age_sec = (label_now - snap_ts).total_seconds()

            # --- Fresh / TTL gating（不要先 early-continue）---
            use_it = False
            is_stale = 0
            if age_sec <= self.fresh_window_sec:
                use_it = True
            elif self.last_known_ttl_sec > 0 and age_sec <= self.last_known_ttl_sec:
                use_it = True
                is_stale = 1

            if not use_it:
                continue

            # 每個裝置只送尚未送過的樣本
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

                all_data.extend(converted)
                sent_candidates_sampling_ts[dev_id] = snap_ts

        if not all_data:
            logger.info("Warm-up: nothing new to send.")
            self._first_send_done = True
            return

        payload = {
            "FUNC": "PushIMAData",
            "version": "6.0",
            "GatewayID": self.gateway_id,
            "Timestamp": label_now.strftime("%Y%m%d%H%M%S"),
            "Data": all_data,
        }

        is_ok: bool = await self._post_with_retry(payload)
        if is_ok:
            # Update label-time dedup and bucket pruning references
            for dev_id in sent_candidates_sampling_ts:
                self.__last_label_ts_by_device[dev_id] = label_now
            self.__last_sent_ts_by_device.update(sent_candidates_sampling_ts)
            await self._prune_buckets()

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

        for i in range(self.__attempt_count):
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.post(self.ima_url, json=payload)
                if self._is_ok(resp):
                    logger.info(f"[POST] ok: {resp.status_code}")
                    return True
                else:
                    logger.warning(f"[POST] not ok (status={resp.status_code}) preview={resp.text[:200]!r}")
            except Exception as e:
                logger.warning(f"[POST] attempt {i+1} failed: {e}")

            if i < len(backoffs):
                await asyncio.sleep(backoffs[i])

        await self._persist_failed_json(payload)
        await self._enforce_resend_storage_budget()
        return False

    async def _resend_failed_files(self) -> None:
        try:
            file_list = sorted(
                [f for f in os.listdir(self.resend_dir) if f.endswith(".json") or re.search(r"\.retry\d+\.json$", f)]
            )
        except FileNotFoundError:
            os.makedirs(self.resend_dir, exist_ok=True)
            file_list = []

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

                async with httpx.AsyncClient(timeout=5.0) as client:
                    if json_obj is not None:
                        resp = await client.post(self.ima_url, json=json_obj)
                    else:
                        resp = await client.post(self.ima_url, data=raw, headers={"Content-Type": "application/json"})

                logger.info(f"[RESEND] {file_name}, resp: {resp.status_code} {resp.text[:120]!r}")

                if self._is_ok(resp):
                    os.remove(file_path)
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
        logger.info(f"Scheduler: anchor={self.anchor_offset_sec}s, interval={self.send_interval_sec}s")
        next_label = self._compute_next_label_time(datetime.now(self._tz))

        while True:
            now = datetime.now(self._tz)
            wait_sec = (next_label - now).total_seconds()
            if wait_sec > 0:
                await asyncio.sleep(wait_sec)

            if self.tick_grace_sec > 0:
                await asyncio.sleep(self.tick_grace_sec)

            await self._resend_failed_files()
            await self._send_at_label_time(next_label)

            next_label = next_label + timedelta(seconds=self.send_interval_sec)

    def _compute_next_label_time(self, now: datetime) -> datetime:
        base = now.replace(microsecond=0)
        # 先對齊到當分鐘錨點
        anchor = int(self.anchor_offset_sec)
        candidate = base.replace(second=anchor)
        interval = float(self.send_interval_sec)

        while candidate <= now:
            candidate += timedelta(seconds=interval)
        return candidate

    async def _send_at_label_time(self, label_time: datetime) -> None:
        latest_by_device = await self._collect_latest_by_device_unlocked()

        all_items: list[dict] = []
        sent_candidates_ts: dict[str, datetime] = {}

        visible_deadline = label_time + timedelta(seconds=self.tick_grace_sec)
        fresh_limit_sec = self.fresh_window_sec

        for dev_id, snap in latest_by_device.items():
            snap_ts: datetime = snap["sampling_ts"]

            # 僅納入「可見窗口」內的樣本（允許 tick 後 grace 期間到達）
            if snap_ts > visible_deadline:
                continue

            age_sec = (label_time - snap_ts).total_seconds()

            # --- Fresh / TTL gating ---
            use_it = False
            is_stale = 0
            if age_sec <= fresh_limit_sec:
                use_it = True
            elif self.last_known_ttl_sec > 0 and age_sec <= self.last_known_ttl_sec:
                use_it = True
                is_stale = 1

            if not use_it:
                continue

            # 每裝置每個 label_time 僅送一次
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

                all_items.extend(converted)
                sent_candidates_ts[dev_id] = snap_ts

        if not all_items:
            if self.heartbeat_on_empty:
                payload = {
                    "FUNC": "PushIMAData",
                    "version": "6.0",
                    "GatewayID": self.gateway_id,
                    "Timestamp": label_time.strftime("%Y%m%d%H%M%S"),
                    "Data": [
                        {"DeviceID": f"{self.gateway_id}_000GW", "Data": {"HB": 1, "report_ts": label_time.isoformat()}}
                    ],
                }

                await self._post_with_retry(payload)
            else:
                logger.info("No fresh data and heartbeat disabled; skip sending.")
            return

        payload = {
            "FUNC": "PushIMAData",
            "version": "6.0",
            "GatewayID": self.gateway_id,
            "Timestamp": label_time.strftime("%Y%m%d%H%M%S"),
            "Data": all_items,
        }

        ok = await self._post_with_retry(payload)
        if ok:
            for dev_id in list(sent_candidates_ts):
                self.__last_label_ts_by_device[dev_id] = label_time
            self.__last_sent_ts_by_device.update(sent_candidates_ts)
            await self._prune_buckets()

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
