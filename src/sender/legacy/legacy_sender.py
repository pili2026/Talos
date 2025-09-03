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
from sender.legacy.legacy_format_adapter import convert_snapshot_to_legacy_payload
from sender.legacy.resend_file_util import (
    extract_retry_count,
    increment_retry_name,
    mark_as_fail,
)
from util.time_util import sleep_until_next_tick

logger = logging.getLogger("LegacySender")


class LegacySenderAdapter:
    """
    Behavior (key points in this version):
      - Warm-up: wait for the first snapshot → send once immediately
        (Timestamp = now; also override item-level time fields to now).
      - Periodic (leading-edge): at each aligned tick (e.g., 00:03:00):
          1) Wait `tick_grace_ms` (default 900 ms) to allow the "current" snapshot to arrive
          2) For each device, pick the "latest visible" snapshot with sampling_ts ≤ (tick + grace)
          3) Deduplicate by using the tick as the label time (each device sends at most once per tick)
          4) Before sending, override each item's time fields to the tick
             (avoid the cloud showing the previous minute)
    """

    def __init__(self, sender_config: dict, device_manager: AsyncDeviceManager):
        self.gateway_id = self._resolve_gateway_id(sender_config["gateway_id"])
        self.resend_dir = sender_config["resend_dir"]
        self.ima_url = sender_config["cloud"]["ima_url"]
        self.send_interval = int(sender_config.get("send_interval_sec", 60))
        self.__attempt_count = int(sender_config.get("attempt_count", 2))
        self.__max_retry = int(sender_config.get("max_retry", 3))

        # NEW: grace time after tick (milliseconds) + acceptable maximum lag (milliseconds)
        self._tick_grace_ms = int(sender_config.get("tick_grace_ms", 900))
        self._fresh_max_lag_ms = int(sender_config.get("fresh_max_lag_ms", 1500))

        self.device_manager = device_manager
        os.makedirs(self.resend_dir, exist_ok=True)

        # window → { device_id → snapshot }; in-memory cache only
        self._latest_per_window: dict[datetime, dict[str, dict]] = defaultdict(dict)
        self._lock = asyncio.Lock()
        self._tz = ZoneInfo("Asia/Taipei")
        self._epoch = datetime(1970, 1, 1, tzinfo=self._tz)

        # ---- Warm-up state ----
        self._first_snapshot_event = asyncio.Event()
        self._first_send_done = False

        # ---- De-dup tracker ----
        # Legacy: last successfully-sent sampling_ts (kept for bucket pruning)
        self._last_sent_ts_by_device: dict[str, datetime] = {}
        # NEW: last sent "label time" (tick or warm-up now) → ensure at most once per device per tick
        self._last_label_ts_by_device: dict[str, datetime] = {}

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

        wstart = LegacySenderAdapter._window_start(sampling_ts, self.send_interval, tz="Asia/Taipei")
        async with self._lock:
            self._latest_per_window[wstart][device_id] = {**snapshot_map, "sampling_ts": sampling_ts}

        if not self._first_snapshot_event.is_set():
            self._first_snapshot_event.set()

    async def start(self):
        """
        Start two background tasks:
          1) _warmup_send_once: wait for the first snapshot → send immediately (unaligned)
          2) _periodic_send_task: aligned by interval → leading-edge send
        """
        asyncio.create_task(self._warmup_send_once())
        asyncio.create_task(self._periodic_send_task())

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
            # Label-time dedup: for the first send use "now" as label time;
            # if we already sent at or after this time for this device, skip it
            last_label = self._last_label_ts_by_device.get(dev_id, self._epoch)
            if label_now <= last_label:
                continue

            last_ts = self._last_sent_ts_by_device.get(dev_id, self._epoch)
            if snap["sampling_ts"] <= last_ts:
                continue

            converted = convert_snapshot_to_legacy_payload(
                gateway_id=self.gateway_id,
                snapshot=snap,
                device_manager=self.device_manager,
            )
            if converted:
                all_data.extend(converted)
                sent_candidates_sampling_ts[dev_id] = snap["sampling_ts"]

        if not all_data:
            logger.info("Warm-up: nothing new to send.")
            self._first_send_done = True
            return

        # Override item-level time fields to "now" (avoid the cloud showing the previous minute)
        self._force_item_timestamp(all_data, report_at=label_now)

        payload = {
            "FUNC": "PushIMAData",
            "version": "6.0",
            "GatewayID": self.gateway_id,
            "Timestamp": label_now.strftime("%Y%m%d%H%M%S"),
            "Data": all_data,
        }

        ok = await self._post_with_retry(payload)
        if ok:
            # Update label-time dedup and bucket pruning references
            for dev_id in sent_candidates_sampling_ts.keys():
                self._last_label_ts_by_device[dev_id] = label_now
            self._last_sent_ts_by_device.update(sent_candidates_sampling_ts)
            await self._prune_buckets()

        self._first_send_done = True

    async def _periodic_send_task(self) -> None:
        """
        Periodic sending loop (leading-edge):
          - Align to the interval using sleep_until_next_tick
          - After the tick, wait the grace period to allow the current value to arrive
          - Attempt to resend previously failed files
          - Send one batch for this tick
        """
        logger.info(f"Start periodic send task every {self.send_interval} seconds (leading-edge)")
        while True:
            tick_dt = await sleep_until_next_tick(self.send_interval, tz="Asia/Taipei")
            # After the tick, wait a grace period so the “current” value has a chance to arrive
            if self._tick_grace_ms > 0:
                await asyncio.sleep(self._tick_grace_ms / 1000)

            logger.info(f"Tick @ {tick_dt.strftime('%Y-%m-%d %H:%M:%S')} (+{self._tick_grace_ms}ms grace)")

            # Handle resend first
            await self._resend_failed_files()

            # Send once for this tick
            await self._send_leading_edge_at_tick(tick_dt)

    async def _send_leading_edge_at_tick(self, tick_dt: datetime) -> None:
        """
        At the tick moment, per device:
          - Pick the latest visible snapshot (sampling_ts ≤ tick + grace)
          - Deduplicate using the tick as "label time" (at most once per device per tick)
          - Before sending, override each item's time fields to the tick (cloud alignment)
        """
        latest_by_device = await self._collect_latest_by_device_unlocked()

        visible_deadline = tick_dt + timedelta(milliseconds=self._tick_grace_ms)
        all_data: list[dict] = []
        sent_candidates_sampling_ts: dict[str, datetime] = {}

        for dev_id, snap in latest_by_device.items():
            snap_ts: datetime = snap["sampling_ts"]

            # Only consider “visible” data before the deadline (including just-arrived data after the tick)
            if snap_ts > visible_deadline:
                continue

            # Deduplicate by "label time = this tick": at most once for this device this minute
            last_label = self._last_label_ts_by_device.get(dev_id, self._epoch)
            if tick_dt <= last_label:
                continue

            # Freshness observation (tunable)
            lag_ms = int((tick_dt - snap_ts).total_seconds() * 1000)
            if lag_ms > self._fresh_max_lag_ms:
                logger.warning(f"[Freshness] {dev_id} lag {lag_ms}ms > {self._fresh_max_lag_ms}ms @ {tick_dt}")

            converted = convert_snapshot_to_legacy_payload(
                gateway_id=self.gateway_id,
                snapshot=snap,
                device_manager=self.device_manager,
            )
            if converted:
                all_data.extend(converted)
                sent_candidates_sampling_ts[dev_id] = snap_ts

        if not all_data:
            logger.info("Leading-edge: no new data at this tick, skip sending.")
            return

        # Override item-level time fields to the tick → ensures the cloud shows “this tick”
        self._force_item_timestamp(all_data, report_at=tick_dt)

        payload = {
            "FUNC": "PushIMAData",
            "version": "6.0",
            "GatewayID": self.gateway_id,
            "Timestamp": tick_dt.strftime("%Y%m%d%H%M%S"),  # packet-level time
            "Data": all_data,
        }

        is_ok = await self._post_with_retry(payload)
        if is_ok:
            # Label time is the tick_dt to ensure the same device won't be sent twice within the same tick
            for dev_id in list(sent_candidates_sampling_ts):
                self._last_label_ts_by_device[dev_id] = tick_dt
            # Keep the original sampling_ts as the reference for bucket pruning
            self._last_sent_ts_by_device.update(sent_candidates_sampling_ts)
            await self._prune_buckets()

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
                    last_ts = self._last_sent_ts_by_device.get(dev_id, self._epoch)
                    if snap_ts <= last_ts:
                        bucket.pop(dev_id, None)
                if not bucket:
                    self._latest_per_window.pop(wstart, None)

    def _force_item_timestamp(self, data_list: list[dict], report_at: datetime) -> None:
        """
        Override each data item's time fields with `report_at`,
        so the cloud display aligns with the intended tick.
        Adjust the key list below based on your converter's actual field names.
        """
        ts_str = report_at.strftime("%Y%m%d%H%M%S")
        for it in data_list:
            for k in ("Timestamp", "Time", "sampleTime", "TS"):
                if k in it:
                    it[k] = ts_str

    async def _post_with_retry(self, payload: dict) -> bool:
        """
        Post `payload` with retries.
          - If response contains "00000" → success
          - On failure, retry up to `attempt_count`
          - If still failing, save the payload into `resend_dir` for later retry
        """
        json_str: str = json.dumps(payload)
        for attempt in range(self.__attempt_count):
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.post(
                        self.ima_url,
                        data=json_str,
                        headers={"Content-Type": "application/json"},
                    )
                logger.info(f"Response: {resp.text}")
                if "00000" not in resp.text:
                    logger.warning(f"[POST] server not OK (status={resp.status_code}). " f"preview={resp.text[:200]!r}")
                return True
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(1)
                if attempt == self.__attempt_count - 1:
                    now_str = datetime.now(self._tz).strftime("%Y%m%d%H%M%S")
                    filename = os.path.join(self.resend_dir, f"resend_{now_str}.json")
                    try:
                        async with aiofiles.open(filename, "w", encoding="utf-8") as f:
                            await f.write(json_str)
                        logger.warning(f"Saved to retry file: {filename}")
                    except Exception as we:
                        logger.error(f"Failed to write retry file {filename}: {we}")
                    return False

    async def _resend_failed_files(self) -> None:
        """
        Try resending files in the `resend` directory:
          - Success (response contains "00000") → delete file
          - Failure and reached the retry limit → rename to .fail
          - Failure but not yet at the limit → increment retry count in filename
        """
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
                    json_str = await f.read()

                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.post(
                        self.ima_url,
                        data=json_str,
                        headers={"Content-Type": "application/json"},
                    )

                logger.info(f"Resend file: {file_name}, response: {resp.text}")

                if "00000" in resp.text:
                    os.remove(file_path)
                    logger.info(f"Resend success, deleted: {file_name}")
                else:
                    if retry_count + 1 >= self.__max_retry:
                        mark_as_fail(file_path)
                        logger.warning(f"Marked as .fail: {file_name}")
                    else:
                        new_name = increment_retry_name(file_name)
                        new_path = os.path.join(self.resend_dir, new_name)
                        os.rename(file_path, new_path)
                        logger.info(f"Retry {retry_count + 1}, renamed to: {new_name}")
            except Exception as e:
                logger.warning(f"Resend failed for {file_name}: {e}")

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
