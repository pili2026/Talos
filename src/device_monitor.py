import asyncio
import logging
from datetime import datetime
from typing import Any

from core.evaluator.constraint_evaluator import ConstraintEvaluator
from core.util.decorator.retry import async_retry
from core.util.pubsub.base import PubSub
from core.util.pubsub.pubsub_topic import PubSubTopic
from core.util.time_util import TIMEZONE_INFO, sleep_exact_interval, sleep_until_next_tick
from device_manager import AsyncDeviceManager


class AsyncDeviceMonitor:
    def __init__(
        self,
        async_device_manager: AsyncDeviceManager,
        pubsub: PubSub,
        interval: float = 1.0,
    ):
        self.async_device_manager = async_device_manager
        self.pubsub = pubsub
        self.interval = interval
        self.logger = logging.getLogger(__class__.__name__)
        self.constraint_evaluate = ConstraintEvaluator(pubsub)

        self.device_configs = {
            f"{device.model}_{device.slave_id}": {
                "device_id": f"{device.model}_{device.slave_id}",
                "model": device.model,
                "type": device.device_type,
                "slave_id": device.slave_id,
            }
            for device in self.async_device_manager.device_list
        }

    async def run(self):
        self.logger.info("Starting device monitor loop...")
        # 1) Poll once at startup (immediately have data available)
        await self._poll_once()

        # 2) Align to the next tick (rounded by interval, e.g., on the minute / every 10 seconds)
        await sleep_until_next_tick(self.interval, tz=TIMEZONE_INFO)

        # 3) Afterwards, maintain a stable rhythm using monotonic clock
        next_mark = None
        while True:
            try:
                await self._poll_once()
                next_mark = await sleep_exact_interval(self.interval, next_mark)
            except Exception as e:
                self.logger.exception(f"Error during polling loop: {e}")
                next_mark = await sleep_exact_interval(self.interval, next_mark)

    async def _poll_once(self):
        raw_data: dict = await self.async_device_manager.read_all_from_all_devices()
        tasks = [self._handle_device(device_id, snapshot) for device_id, snapshot in raw_data.items()]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        for device_id, result in zip(raw_data.keys(), results):
            if isinstance(result, Exception):
                self.logger.error(f"[{device_id}] Task failed: {result}")

    @async_retry(logger=logging.getLogger("AsyncDeviceMonitor"))
    async def _handle_device(self, device_id: str, snapshot: dict):
        config = self.device_configs.get(device_id)
        if config is None:
            self.logger.warning(f"[{device_id}] No config found, skipping.")
            return

        pretty_map: dict[Any, str] = {k: f"{v:.3f}" if v is not None else "None" for k, v in snapshot.items()}
        self.logger.info(f"[{device_id}] Snapshot: {pretty_map}")

        payload = {
            "device_id": config["device_id"],
            "model": config["model"],
            "type": config["type"],
            "slave_id": config["slave_id"],
            "sampling_ts": datetime.now(TIMEZONE_INFO),
            "values": snapshot,
            "device": self.async_device_manager.get_device_by_model_and_slave_id(config["model"], config["slave_id"]),
        }

        await self.pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, payload)
