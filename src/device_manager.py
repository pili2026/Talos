import logging
import os

import yaml
from pymodbus.client import AsyncModbusSerialClient

from generic_device import AsyncGenericModbusDevice

logger = logging.getLogger("DeviceManager")


class AsyncDeviceManager:
    def __init__(self, config_path: str = "./res/modbus_device.yml", model_base_path: str = "./res"):
        self.device_list = []
        self.client_dict = {}
        self.config_path = config_path
        self.model_base_path = model_base_path

    async def init(self):
        with open(self.config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        for device_conf in config.get("devices", []):
            model_path = os.path.join(self.model_base_path, device_conf["model_file"])
            with open(model_path, "r", encoding="utf-8") as mf:
                model_conf = yaml.safe_load(mf)

            port = device_conf["port"]
            if port not in self.client_dict:
                client = AsyncModbusSerialClient(port=port, baudrate=9600, timeout=1)
                connected = await client.connect()
                if not connected:
                    logger.warning(f"Failed to connect to port {port}")
                self.client_dict[port] = client

            device_key = f"{device_conf['id']}_{device_conf['slave_id']}"
            device = AsyncGenericModbusDevice(
                device_id=device_key,
                client=self.client_dict[port],
                slave_id=device_conf["slave_id"],
                register_type=model_conf.get("register_type", "holding"),
                address=model_conf["register_map"],
                model=model_conf.get("model", device_conf["id"]),
            )
            self.device_list.append(device)

    async def read_all_from_all_devices(self):
        result = {}
        for device in self.device_list:
            result[device.device_id] = await device.read_all()
        return result

    def get_device_by_id(self, device_id: str) -> AsyncGenericModbusDevice | None:
        for device in self.device_list:
            if device.device_id == device_id:
                return device
        return None
