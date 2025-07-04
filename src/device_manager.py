import logging
import os

import yaml
from pymodbus.client import ModbusSerialClient

from generic_device import GenericModbusDevice

logger = logging.getLogger("DeviceManager")


class DeviceManager:
    def __init__(self, config_path: str, model_base_path: str):
        self.devices = []
        self.clients = {}  # key: port, value: shared ModbusSerialClient

        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        for device_conf in config.get("devices", []):
            model_path = os.path.join(model_base_path, device_conf["model_file"])
            with open(model_path, "r") as mf:
                model_conf = yaml.safe_load(mf)

            port = device_conf["port"]
            if port not in self.clients:
                self.clients[port] = ModbusSerialClient(port=port, baudrate=9600, timeout=1)

            device = GenericModbusDevice(
                device_id=device_conf["id"],
                client=self.clients[port],
                slave_id=device_conf["slave_id"],
                register_type=model_conf.get("register_type", "holding"),
                pins=model_conf["pins"],
                model=model_conf.get("model", device_conf["id"]),
            )
            self.devices.append(device)

    def read_all_from_all_devices(self):
        result = {}
        for device in self.devices:
            result[device.device_id] = device.read_all()
        return result
