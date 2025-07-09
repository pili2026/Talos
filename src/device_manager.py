import logging
import os

import yaml
from pymodbus.client import ModbusSerialClient

from generic_device import GenericModbusDevice

logger = logging.getLogger("DeviceManager")


class DeviceManager:
    def __init__(self, config_path: str, model_base_path: str):
        self.device_list = []
        self.client_dict = {}

        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        for device_conf in config.get("devices", []):
            model_path = os.path.join(model_base_path, device_conf["model_file"])
            with open(model_path, "r", encoding="utf-8") as mf:
                model_conf = yaml.safe_load(mf)

            port = device_conf["port"]
            if port not in self.client_dict:
                self.client_dict[port] = ModbusSerialClient(port=port, baudrate=9600, timeout=1)

            device = GenericModbusDevice(
                device_id=device_conf["id"],
                client=self.client_dict[port],
                slave_id=device_conf["slave_id"],
                register_type=model_conf.get("register_type", "holding"),
                pins=model_conf["pins"],
                model=model_conf.get("model", device_conf["id"]),
            )
            self.device_list.append(device)

    def read_all_from_all_devices(self):
        result = {}
        for device in self.device_list:
            result[device.device_id] = device.read_all()
        return result
