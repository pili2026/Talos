import asyncio
import logging
from datetime import datetime

from alert_controller import AlertEvaluator
from device_manager import AsyncDeviceManager
from model.alert_message import AlertMessage
from util.config_loader import load_yaml_file
from util.pubsub.base import PubSub


class DeviceMonitor:
    def __init__(
        self,
        async_device_manager: AsyncDeviceManager,
        pubsub: PubSub,
        alert_config: str = "res/alert_condition.yml",
        interval: float = 1.0,
    ):
        self.async_device_manager = async_device_manager
        self.interval = interval
        self.logger = logging.getLogger("DeviceMonitor")
        self.alert_config = load_yaml_file(alert_config)
        self.alert_evaluator = AlertEvaluator(self.alert_config)
        self.pubsub = pubsub

    async def run(self):
        self.logger.info("Starting device monitor loop...")
        while True:
            try:
                all_data = await self.async_device_manager.read_all_from_all_devices()

                for device_id, value_map in all_data.items():
                    pretty_map = {k: f"{v:.3f}" for k, v in value_map.items()}
                    self.logger.info(f"[{device_id}] {pretty_map}")

                    # Evaluate alerts
                    alerts = self.alert_evaluator.evaluate(value_map)
                    for alert_msg in alerts:
                        self.logger.warning(f"[{device_id}] {alert_msg}")
                        alert = AlertMessage(
                            device_id=device_id, level="WARNING", message=alert_msg, timestamp=datetime.now()
                        )
                        await self.pubsub.publish("alert.warning", alert)

                await asyncio.sleep(self.interval)

            except Exception as e:
                self.logger.exception(f"Error during polling: {e}")
                await asyncio.sleep(self.interval)
