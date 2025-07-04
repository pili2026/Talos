import logging
import time

from device_manager import DeviceManager


class DeviceMonitor:
    def __init__(self, device_manager: DeviceManager, interval: float = 1.0):
        self.device_manager = device_manager
        self.interval = interval
        self.logger = logging.getLogger("DeviceMonitor")

    def run(self):
        self.logger.info("Starting device monitor loop...")
        while True:
            try:
                all_data = self.device_manager.read_all_from_all_devices()
                for device_id, value_map in all_data.items():
                    self.logger.info(f"[{device_id}] {value_map}")
                time.sleep(self.interval)
            except Exception as e:
                self.logger.exception(f"Error during polling: {e}")
                time.sleep(self.interval)
