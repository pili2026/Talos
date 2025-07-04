from device_manager import DeviceManager
from device_monitor import DeviceMonitor

if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO)

    mgr = DeviceManager(config_path="./res/modbus_device.yml", model_base_path="./res")

    monitor = DeviceMonitor(mgr)
    monitor.run()
