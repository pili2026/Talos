import logging

from device_manager import DeviceManager
from device_monitor import DeviceMonitor
from util.logger_config import setup_logging

if __name__ == "__main__":
    setup_logging(
        log_level=logging.INFO,
        log_to_file=True,
        log_dir="logs",  # logs/
        log_base_filename="talos",  # talos.log, talos.log.2025-07-10
        when="midnight",  # Everyday 00:00 rotate
        backup_count=14,  # Keep 14 days of logs
    )

    # TODO: Use environment variables or command line args for config paths
    mgr = DeviceManager(config_path="./res/modbus_device.yml", model_base_path="./res")

    # TODO: Use environment variables or command line args for config paths
    monitor = DeviceMonitor(mgr, alert_config="res/alert_condition.yml", interval=1.0)
    monitor.run()
