import asyncio
import logging
from datetime import datetime

from alert_evaluator import AlertEvaluator
from device_manager import AsyncDeviceManager
from model.alert_message import AlertMessage
from util.config_loader import ConfigManager
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
        self.pubsub = pubsub
        self.interval = interval
        self.logger = logging.getLogger("DeviceMonitor")

        self.alert_config = ConfigManager.load_yaml_file(alert_config)
        self.alert_evaluator = AlertEvaluator(self.alert_config)

        self.device_configs = {
            device.device_id: {
                "model": device.model,
                "pins": device.pins,
                "slave_id": device.slave_id,
            }
            for device in self.async_device_manager.device_list
        }

    async def run(self):
        self.logger.info("Starting device monitor loop...")
        while True:
            try:
                raw_data: dict = await self.async_device_manager.read_all_from_all_devices()

                for device_key, snapshot in raw_data.items():
                    # NOTE: device_key = model + selave_id
                    config: dict = self.device_configs.get(device_key)
                    if config is None:
                        self.logger.warning(f"[{device_key}] No config found, skipping.")
                        continue

                    pretty_map = {k: f"{v:.3f}" for k, v in snapshot.items()}
                    self.logger.info(f"[{device_key}] Snapshot: {pretty_map}")

                    alerts = self.alert_evaluator.evaluate(
                        model=config["model"],
                        snapshot=snapshot,
                        pins=config["pins"],
                    )

                    for alert_code, alert_msg in alerts:
                        self.logger.warning(f"[{device_key}] {alert_msg}")
                        alert = AlertMessage(
                            device_key=device_key,
                            level="WARNING",
                            message=alert_msg,
                            alert_code=alert_code,
                            timestamp=datetime.now(),
                        )
                        await self.pubsub.publish("alert.warning", alert)

                await asyncio.sleep(self.interval)

            except Exception as e:
                self.logger.exception(f"Error during polling: {e}")
                await asyncio.sleep(self.interval)
