import asyncio
import json
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from device_manager import AsyncDeviceManager
from sender.legacy.legacy_format_adapter import convert_snapshot_to_legacy_payload

logger = logging.getLogger("LegacySender")


class LegacySenderAdapter:
    def __init__(self, sender_config: dict, device_manager: AsyncDeviceManager):
        self.gateway_id = sender_config["gateway_id"][:11]
        self.resend_dir = sender_config["resend_dir"]
        self.ima_url = sender_config["cloud"]["ima_url"]
        self.send_interval = sender_config.get("send_interval_sec", 60)
        self.device_manager = device_manager
        os.makedirs(self.resend_dir, exist_ok=True)

        self._latest_snapshots: dict[str, dict] = {}
        self._lock = asyncio.Lock()

    async def handle_snapshot(self, snapshot_map: dict) -> None:
        device_id = snapshot_map.get("device_id")
        if not device_id:
            logger.warning(f"[{__class__.__name__}] Missing device_id in snapshot: {snapshot_map}")
            return

        async with self._lock:
            self._latest_snapshots[device_id] = snapshot_map

    async def start(self):
        asyncio.create_task(self._periodic_send_task())

    async def _periodic_send_task(self):
        logger.info(f"[{__class__.__name__}] Start periodic send task every {self.send_interval} seconds")
        while True:
            await self._sleep_until_next_interval()

            async with self._lock:
                if not self._latest_snapshots:
                    logger.info(f"[{__class__.__name__}] No snapshot to send")
                    continue

                # Transition use
                snapshot_list = list(self._latest_snapshots.values())
                self._latest_snapshots.clear()

            logger.info(f"[{__class__.__name__}] Start periodic task: object_id={id(self)}")
            await self.send_to_cloud(snapshot_list)

    async def _sleep_until_next_interval(self, tz: str = "Asia/Taipei"):
        time_zone = ZoneInfo(tz)
        now = datetime.now(time_zone)
        ts = int(now.timestamp())
        next_ts = ((ts // self.send_interval) + 1) * self.send_interval
        next_tick = datetime.fromtimestamp(next_ts, tz=time_zone)

        sleep_time = (next_tick - now).total_seconds()

        logger.info(
            f"[{__class__.__name__}] Sleep until {next_tick.strftime('%Y-%m-%d %H:%M:%S')} ({sleep_time:.2f} sec)"
        )
        await asyncio.sleep(sleep_time)

    async def send_to_cloud(self, snapshot_list: list[dict]) -> None:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        all_data = []

        for snapshot in snapshot_list:
            converted: dict = convert_snapshot_to_legacy_payload(
                gateway_id=self.gateway_id, snapshot=snapshot, device_manager=self.device_manager
            )
            all_data.extend(converted)

        payload = {
            "FUNC": "PushIMAData",
            "version": "6.0",
            "GatewayID": self.gateway_id,
            "Timestamp": timestamp,
            "CommandID": 0,
            "Data": all_data,
        }

        json_str: str = json.dumps(payload)

        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.post(
                        self.ima_url,
                        data=json_str,
                        headers={"Content-Type": "application/json"},
                    )
                    logger.info(f"[{__class__.__name__}] Response: {resp.text}")

                    if "00000" not in resp.text:
                        raise ValueError("Server response error")
                    break

            except Exception as e:
                logger.warning(f"[{__class__.__name__}] Attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(1)

                if attempt == 1:
                    filename = os.path.join(self.resend_dir, "manualtest-resend.xms")
                    with open(filename, "w", encoding="utf-8") as f:
                        f.write(json_str)
                    logger.warning(f"[{__class__.__name__}] Saved to retry file: {filename}")
