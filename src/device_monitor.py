import logging
import time

from alert_controller import AlertEvaluator
from device_manager import DeviceManager
from util.config_loader import load_yaml_file


class DeviceMonitor:
    def __init__(
        self, device_manager: DeviceManager, alert_config: str = "res/alert_condition.yml", interval: float = 1.0
    ):
        self.device_manager = device_manager
        self.interval = interval
        self.logger = logging.getLogger("DeviceMonitor")
        self.alert_config = load_yaml_file(alert_config)
        self.alert_evaluator = AlertEvaluator(self.alert_config)

    def run(self):
        self.logger.info("Starting device monitor loop...")
        while True:
            try:
                all_data = self.device_manager.read_all_from_all_devices()

                for device_id, value_map in all_data.items():
                    pretty_map = {k: f"{v:.3f}" for k, v in value_map.items()}
                    self.logger.info(f"[{device_id}] {pretty_map}")

                    # Evaluate alerts
                    alerts = self.alert_evaluator.evaluate(value_map)
                    for alert_msg in alerts:
                        self.logger.warning(f"[{device_id}] {alert_msg}")  # or .error() if critical

                time.sleep(self.interval)

            except Exception as e:
                self.logger.exception(f"Error during polling: {e}")
                time.sleep(self.interval)
