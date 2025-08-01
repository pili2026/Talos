import logging
import os

from pymodbus.client import AsyncModbusSerialClient

from generic_device import AsyncGenericModbusDevice
from util.config_manager import ConfigManager

logger = logging.getLogger("DeviceManager")


class AsyncDeviceManager:
    def __init__(self, config_path: str, instance_config: dict, model_base_path: str = "./res"):
        self.device_list: list[AsyncGenericModbusDevice] = []
        self.client_dict = {}
        self.config_path = config_path
        self.instance_config = instance_config
        self.model_base_path = model_base_path

    async def init(self):
        config: dict = ConfigManager().load_yaml_file(self.config_path)

        for device_conf in config.get("devices", []):
            model_path: str = os.path.join(self.model_base_path, device_conf["model_file"])
            model_config: dict = ConfigManager().load_yaml_file(model_path)

            model: str = model_config["model"]
            slave_id: str = device_conf["slave_id"]
            port: str = device_conf["port"]

            if port not in self.client_dict:
                client = AsyncModbusSerialClient(port=port, baudrate=9600, timeout=1)
                connected: bool = await client.connect()
                if not connected:
                    logger.warning(f"Failed to connect to port {port}")
                self.client_dict[port] = client

            model_constraints: dict = model_config.get("constraints", {})
            instance_constraints: dict = ConfigManager.get_instance_constraints(self.instance_config, model, slave_id)
            final_constraints = {**model_constraints, **instance_constraints}

            device = AsyncGenericModbusDevice(
                model=model,
                client=self.client_dict[port],
                slave_id=slave_id,
                register_type=model_config.get("register_type", "holding"),
                register_map=model_config["register_map"],
                constraints=final_constraints,
            )
            self.device_list.append(device)

    async def read_all_from_all_devices(self):
        result = {}
        for device in self.device_list:
            key = f"{device.model}_{device.slave_id}"
            result[key] = await device.read_all()
        return result

    def get_device_by_model_and_slave_id(self, model: str, slave_id: str) -> AsyncGenericModbusDevice | None:
        for device in self.device_list:
            if device.model == model and device.slave_id == slave_id:
                return device
        return None
