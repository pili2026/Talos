import asyncio
import logging
from datetime import datetime

from alert_evaluator import AlertEvaluator
from control_evaluator import ControlActionModel, ControlEvaluator
from control_executor import ControlExecutor
from device_manager import AsyncDeviceManager
from model.alert_model import AlertConfig, AlertMessageModel, AlertSeverity
from util.config_manager import ConfigManager
from util.decorator.retry import async_retry
from util.pubsub.base import PubSub
from util.pubsub.pubsub_topic import PubSubTopic


# FIXME: Need decouple to refactor interdependency with control logic
class AsyncDeviceMonitor:
    def __init__(
        self,
        async_device_manager: AsyncDeviceManager,
        pubsub: PubSub,
        alert_config: str = "res/alert_condition.yml",
        control_config: str = "res/control_condition.yml",
        interval: float = 1.0,
    ):
        self.async_device_manager = async_device_manager
        self.pubsub = pubsub
        self.interval = interval
        self.logger = logging.getLogger("DeviceMonitor")

        alert_config_dict = ConfigManager.load_yaml_file(alert_config)
        self.alert_config = AlertConfig.model_validate(alert_config_dict)
        self.alert_evaluator = AlertEvaluator(self.alert_config)

        self.device_configs = {
            f"{device.model}_{device.slave_id}": {
                "model": device.model,
                "register_map": device.register_map,
                "slave_id": device.slave_id,
            }
            for device in self.async_device_manager.device_list
        }

        self.control_config = ConfigManager.load_yaml_file(control_config)
        self.control_evaluator = ControlEvaluator(self.control_config)
        self.control_executor = ControlExecutor(async_device_manager)

    async def run(self):
        self.logger.info("Starting device monitor loop...")
        while True:
            try:
                raw_data: dict = await self.async_device_manager.read_all_from_all_devices()

                tasks = [self._handle_device(device_id, snapshot) for device_id, snapshot in raw_data.items()]

                results = await asyncio.gather(*tasks, return_exceptions=False)

                for device_id, result in zip(raw_data.keys(), results):
                    if isinstance(result, Exception):
                        self.logger.error(f"[{device_id}] Task failed: {result}")

                await asyncio.sleep(self.interval)

            except Exception as e:
                self.logger.exception(f"Error during polling loop: {e}")
                await asyncio.sleep(self.interval)

    @async_retry(logger=logging.getLogger("DeviceMonitor"))
    async def _handle_device(self, device_id: str, snapshot: dict):
        config: dict = self.device_configs.get(device_id)
        if config is None:
            self.logger.warning(f"[{device_id}] No config found, skipping.")
            return

        pretty_map = {k: f"{v:.3f}" for k, v in snapshot.items()}
        self.logger.info(f"[{device_id}] Snapshot: {pretty_map}")

        # Alert evaluation
        alert_list = self.alert_evaluator.evaluate(device_id=device_id, snapshot=snapshot)
        for alert_code, alert_msg in alert_list:
            self.logger.warning(f"[{device_id}] {alert_msg}")
            alert = AlertMessageModel(
                device_key=device_id,
                level=AlertSeverity.WARNING,
                message=alert_msg,
                alert_code=alert_code,
                timestamp=datetime.now(),
            )
            await self.pubsub.publish(PubSubTopic.ALERT_WARNING, alert)

        # Control evaluation
        control_action_list: list[ControlActionModel] = self.control_evaluator.evaluate(
            device_id=device_id, snapshot=snapshot
        )
        if control_action_list:
            self.logger.info(f"[{device_id}] Control actions: {control_action_list}")
            await self.control_executor.execute(control_action_list)
