import logging
import os
from typing import Any

from pymodbus.client import AsyncModbusSerialClient

from generic_device import AsyncGenericModbusDevice
from util.config_manager import ConfigManager

logger = logging.getLogger("DeviceManager")


def _deep_merge_dicts(base: dict, override: dict) -> dict:
    """Shallow-safe deep merge for 2-level dicts (enough for modes tables)."""
    if not isinstance(base, dict):
        base = {}
    if not isinstance(override, dict):
        return dict(base)
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            nested = dict(out[k])
            nested.update(v)
            out[k] = nested
        else:
            out[k] = v
    return out


class AsyncDeviceManager:
    def __init__(self, config_path: str, instance_config: dict, model_base_path: str = "./res"):
        self.device_list: list[AsyncGenericModbusDevice] = []
        self.client_dict: dict[str, AsyncModbusSerialClient] = {}
        self.config_path = config_path
        self.instance_config = instance_config
        self.model_base_path = model_base_path

    async def init(self):
        config: dict = ConfigManager().load_yaml_file(self.config_path)

        for device_conf in config.get("devices", []):
            model_path: str = os.path.join(self.model_base_path, device_conf["model_file"])
            model_config: dict = ConfigManager().load_yaml_file(model_path)

            model: str = model_config["model"]
            # cast slave_id to int to be safe for pymodbus
            slave_id: int = int(device_conf["slave_id"])
            port: str = device_conf["port"]
            device_type: str = device_conf["type"]

            if port not in self.client_dict:
                client = AsyncModbusSerialClient(port=port, baudrate=9600, timeout=1)
                connected: bool = await client.connect()
                if not connected:
                    logger.warning(f"Failed to connect to port {port}")
                self.client_dict[port] = client

            # constraints: model-level + instance-level override
            model_constraints: dict = model_config.get("constraints", {})
            instance_constraints: dict = ConfigManager.get_instance_constraints(self.instance_config, model, slave_id)
            final_constraints = {**model_constraints, **instance_constraints}

            # NEW: pass tables/modes into device; allow per-device override of modes in devices[].modes
            model_tables: dict = model_config.get("tables", {})
            model_modes: dict = model_config.get("modes", {})
            instance_modes_override: dict = device_conf.get("modes", {})  # optional per-instance MV switch, etc.
            final_modes: dict = _deep_merge_dicts(model_modes, instance_modes_override)

            device = AsyncGenericModbusDevice(
                model=model,
                client=self.client_dict[port],
                slave_id=slave_id,
                register_type=model_config.get("register_type", "holding"),
                register_map=model_config["register_map"],
                constraints=final_constraints,
                device_type=device_type,
                tables=model_tables,
                modes=final_modes,
                write_hooks=model_config.get("write_hooks", []),
            )
            self.device_list.append(device)

    async def read_all_from_all_devices(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for device in self.device_list:
            key = f"{device.model}_{device.slave_id}"
            result[key] = await device.read_all()
        return result

    # TODO: Determine if slave_id should be str or int
    def get_device_by_model_and_slave_id(self, model: str, slave_id: str | int) -> AsyncGenericModbusDevice | None:
        sid = int(slave_id) if isinstance(slave_id, str) else slave_id
        for device in self.device_list:
            if device.model == model and device.slave_id == sid:
                return device
        return None
