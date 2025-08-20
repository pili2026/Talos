import asyncio
import json
import logging
import os
import re
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
    def __init__(self, sender_config: dict, device_manager: AsyncDeviceManager):
        self.gateway_id = sender_config["gateway_id"][:11]
        self.resend_dir = sender_config["resend_dir"]
        self.ima_url = sender_config["cloud"]["ima_url"]
        self.send_interval = sender_config.get("send_interval_sec", 60)
        self.__attempt_count = sender_config.get("attempt_count", 2)
        self.__max_retry = sender_config.get("max_retry", 3)
        self.__grace_period_sec = sender_config.get("grace_period_sec", 3)
        self.device_manager = device_manager
        os.makedirs(self.resend_dir, exist_ok=True)

        # window → { device_id → snapshot }; keep only the last snapshot per device per window
        self._latest_per_window: dict[datetime, dict[str, dict]] = defaultdict(dict)
        self._lock = asyncio.Lock()
        self._tz = ZoneInfo("Asia/Taipei")

    async def handle_snapshot(self, snapshot_map: dict) -> None:
        device_id = snapshot_map.get("device_id")
        sampling_ts: datetime = snapshot_map.get("sampling_ts")
        if not device_id or not sampling_ts:
            logger.warning(f"[LegacySender] Missing device_id or sampling_ts in snapshot: {snapshot_map}")
            return

        wstart = LegacySenderAdapter._window_start(sampling_ts, self.send_interval, tz="Asia/Taipei")
        async with self._lock:
            # For the same window, keep only the last snapshot per device
            self._latest_per_window[wstart][device_id] = snapshot_map

    async def start(self):
        asyncio.create_task(self._periodic_send_task())

    async def _periodic_send_task(self):
        logger.info(f"Start periodic send task every {self.send_interval} seconds")
        while True:
            # Align to the next tick (wall clock)
            next_tick = await sleep_until_next_tick(self.send_interval, tz="Asia/Taipei")
            logger.info(f"Wake at {next_tick.strftime('%Y-%m-%d %H:%M:%S')}")

            # Step 1: handle resend first
            await self._resend_failed_files()

            # Step 2: flush finished windows (with grace period)
            now = datetime.now(self._tz)
            cutoff = now - timedelta(seconds=self.__grace_period_sec)

            to_flush: list[tuple[datetime, dict[str, dict]]] = []
            async with self._lock:
                for wstart in sorted(self._latest_per_window.keys()):
                    wend = wstart + timedelta(seconds=self.send_interval)
                    if wend <= cutoff:
                        to_flush.append((wstart, self._latest_per_window.pop(wstart)))

            for wstart, bucket in to_flush:
                await self._flush_window(wstart, bucket)

    async def _flush_window(self, wstart: datetime, bucket: dict[str, dict]) -> None:
        wend = wstart + timedelta(seconds=self.send_interval)
        timestamp = wend.strftime("%Y%m%d%H%M%S")  # use window end for alignment

        all_data = []
        # For each device, send only the last snapshot within the window (keep original "last only" strategy)
        for snap in bucket.values():
            converted: list[dict] = convert_snapshot_to_legacy_payload(
                gateway_id=self.gateway_id,
                snapshot=snap,
                device_manager=self.device_manager,
            )
            all_data.extend(converted)

        if not all_data:
            logger.info(f"Window {wstart} has no data, skip sending.")
            return

        payload = {
            "FUNC": "PushIMAData",
            "version": "6.0",
            "GatewayID": self.gateway_id,
            "Timestamp": timestamp,  # ← changed to window end
            "Data": all_data,
        }

        await self._post_with_retry(payload)

    async def _post_with_retry(self, payload: dict) -> None:
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
                break
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(1)
                if attempt == self.__attempt_count - 1:
                    now_str = datetime.now(self._tz).strftime("%Y%m%d%H%M%S")
                    filename = os.path.join(self.resend_dir, f"resend_{now_str}.json")
                    async with aiofiles.open(filename, "w", encoding="utf-8") as f:
                        await f.write(json_str)
                    logger.warning(f"Saved to retry file: {filename}")

    async def _resend_failed_files(self) -> None:
        file_list = sorted(
            [f for f in os.listdir(self.resend_dir) if f.endswith(".json") or re.search(r"\.retry\d+\.json$", f)]
        )

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
        """Align sampling_ts to the start of its tumbling window."""
        ts_tz = ts.astimezone(ZoneInfo(tz)).replace(microsecond=0)
        ival = int(interval_sec)
        sec = (ts_tz.second // ival) * ival
        return ts_tz.replace(second=sec)
