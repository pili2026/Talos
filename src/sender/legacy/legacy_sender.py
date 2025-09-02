import asyncio
import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime
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
    Behavior:
      - Warm-up: wait for the first snapshot → send once immediately (Timestamp = now).
      - Periodic (leading-edge): at each aligned tick (e.g., 00:03:00) → send the *current latest* record per device
        (Timestamp = the tick time), instead of the previous full window (no trailing window).
      - De-dup: use the per-device last successfully sent timestamp to avoid resending the same snapshot.
    """

    def __init__(self, sender_config: dict, device_manager: AsyncDeviceManager):
        self.gateway_id = sender_config["gateway_id"][:11]
        self.resend_dir = sender_config["resend_dir"]
        self.ima_url = sender_config["cloud"]["ima_url"]
        self.send_interval = int(sender_config.get("send_interval_sec", 60))
        self.__attempt_count = int(sender_config.get("attempt_count", 2))
        self.__max_retry = int(sender_config.get("max_retry", 3))

        self.device_manager = device_manager
        os.makedirs(self.resend_dir, exist_ok=True)

        # window → { device_id → snapshot }; used only as an in-memory cache
        self._latest_per_window: dict[datetime, dict[str, dict]] = defaultdict(dict)
        self._lock = asyncio.Lock()
        self._tz = ZoneInfo("Asia/Taipei")
        self._epoch = datetime(1970, 1, 1, tzinfo=self._tz)

        # ---- Warm-up state ----
        self._first_snapshot_event = asyncio.Event()
        self._first_send_done = False

        # ---- De-dup tracker ----
        # device_id → last successfully sent sampling_ts (tz-aware)
        self._last_sent_ts_by_device: dict[str, datetime] = {}

    async def handle_snapshot(self, snapshot_map: dict) -> None:
        """
        When a snapshot arrives, put it into the bucket for its window (keep only the last per device),
        and trigger warm-up when the first one arrives.
        """
        device_id = snapshot_map.get("device_id")
        sampling_ts: datetime | None = snapshot_map.get("sampling_ts")

        if not device_id or not sampling_ts:
            logger.warning(f"[LegacySender] Missing device_id or sampling_ts in snapshot: {snapshot_map}")
            return

        # Ensure tz-aware; if an external naive datetime is given, set Asia/Taipei
        if sampling_ts.tzinfo is None:
            sampling_ts = sampling_ts.replace(tzinfo=self._tz)
        else:
            sampling_ts = sampling_ts.astimezone(self._tz)

        wstart = LegacySenderAdapter._window_start(sampling_ts, self.send_interval, tz="Asia/Taipei")
        async with self._lock:
            # For the same window, keep only the last snapshot per device
            self._latest_per_window[wstart][device_id] = {**snapshot_map, "sampling_ts": sampling_ts}

        # First snapshot arrived → notify warm-up
        if not self._first_snapshot_event.is_set():
            self._first_snapshot_event.set()

    async def start(self):
        """
        Launch two background tasks:
          1) _warmup_send_once: wait for the first snapshot → send once immediately (not aligned)
          2) _periodic_send_task: align to whole minutes/intervals → send the single *latest at the moment* (leading-edge)
        """
        asyncio.create_task(self._warmup_send_once())
        asyncio.create_task(self._periodic_send_task())

    async def _warmup_send_once(self, timeout_sec: int = 15, debounce_s: int = 1) -> None:
        try:
            await asyncio.wait_for(self._first_snapshot_event.wait(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            logger.info("Warm-up: no snapshot within timeout; skip immediate send.")
            return

        if debounce_s > 0:
            await asyncio.sleep(debounce_s)

        latest_by_device = await self._collect_latest_by_device_unlocked()

        # Filter out data already sent or not updated
        all_data: list[dict] = []
        sent_candidates: dict[str, datetime] = {}
        for dev_id, snap in latest_by_device.items():
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
                sent_candidates[dev_id] = snap["sampling_ts"]

        if not all_data:
            logger.info("Warm-up: nothing new to send.")
            self._first_send_done = True
            return

        payload = {
            "FUNC": "PushIMAData",
            "version": "6.0",
            "GatewayID": self.gateway_id,
            "Timestamp": datetime.now(self._tz).strftime("%Y%m%d%H%M%S"),  # not aligned; use current time
            "Data": all_data,
        }

        ok = await self._post_with_retry(payload)
        if ok:
            self._last_sent_ts_by_device.update(sent_candidates)
            await self._prune_buckets()
        self._first_send_done = True

    async def _periodic_send_task(self) -> None:
        logger.info(f"Start periodic send task every {self.send_interval} seconds (leading-edge)")
        while True:
            tick_dt = await sleep_until_next_tick(self.send_interval, tz="Asia/Taipei")
            logger.info(f"Tick @ {tick_dt.strftime('%Y-%m-%d %H:%M:%S')}")

            # Handle resend first
            await self._resend_failed_files()

            # At the aligned tick, send the *current latest* one per device
            await self._send_leading_edge_at_tick(tick_dt)

    async def _send_leading_edge_at_tick(self, tick_dt: datetime) -> None:
        """
        At the tick time, aggregate the currently latest snapshot (sampling_ts <= tick_dt) for every device,
        and send only those newer than the device's last successful send timestamp.
        The payload Timestamp = tick_dt (aligned time).
        """
        latest_by_device = await self._collect_latest_by_device_unlocked()

        all_data: list[dict] = []
        sent_candidates: dict[str, datetime] = {}

        for dev_id, snap in latest_by_device.items():
            # Only send what is visible at this tick: avoid including samples that arrive after the tick
            if snap["sampling_ts"] > tick_dt:
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
                sent_candidates[dev_id] = snap["sampling_ts"]

        if not all_data:
            logger.info("Leading-edge: no new data at this tick, skip sending.")
            return

        payload = {
            "FUNC": "PushIMAData",
            "version": "6.0",
            "GatewayID": self.gateway_id,
            "Timestamp": tick_dt.strftime("%Y%m%d%H%M%S"),  # aligned: use tick time
            "Data": all_data,
        }

        is_ok = await self._post_with_retry(payload)
        if is_ok:
            self._last_sent_ts_by_device.update(sent_candidates)
            await self._prune_buckets()

    # -------------------------
    # Helpers
    # -------------------------
    async def _collect_latest_by_device_unlocked(self) -> dict[str, dict]:
        """
        Reduce all buckets into the single *currently latest* snapshot for each device.
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
        Remove snapshots that have already been sent (or are older), to prevent unbounded bucket growth.
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

    async def _post_with_retry(self, payload: dict) -> bool:
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
                    raise ValueError("Server response error")
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
        Try resending files in the resend directory first:
          - If successful (contains "00000"), delete the file
          - If failed and the limit is reached, mark it as .fail
          - If failed but still under the limit, increment retry count (rename)
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
        """Align sampling_ts to the start of its tumbling window (used only for internal bucketing)."""
        ts_tz = ts.astimezone(ZoneInfo(tz)).replace(microsecond=0)
        ival = int(interval_sec)
        sec = (ts_tz.second // ival) * ival
        return ts_tz.replace(second=sec)
