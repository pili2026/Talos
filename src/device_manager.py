import logging
import os
from typing import Any

from pymodbus.client import AsyncModbusSerialClient

from device.generic.constraints_policy import ConstraintPolicy
from device.generic.generic_device import AsyncGenericModbusDevice
from schema.constraint_schema import ConstraintConfig, ConstraintConfigSchema
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
    def __init__(
        self, config_path: str, constraint_config_schema: ConstraintConfigSchema, model_base_path: str = "./res"
    ):
        self.device_list: list[AsyncGenericModbusDevice] = []
        self.client_dict: dict[str, AsyncModbusSerialClient] = {}
        self.config_path = config_path
        self.constraint_config_schema = constraint_config_schema
        self.model_base_path = model_base_path

        self.driver_config_by_model: dict[str, dict] = {}

    async def init(self):
        config: dict = ConfigManager().load_yaml_file(self.config_path)

        for device_config in config.get("devices", []):
            model_path: str = os.path.join(self.model_base_path, device_config["model_file"])
            model_config: dict = ConfigManager().load_yaml_file(model_path)

            model: str = model_config["model"]
            if model not in self.driver_config_by_model:
                # NOTE: Check model_config reference to avoid re-loading same model file
                self.driver_config_by_model[model] = model_config

            # cast slave_id to int to be safe for pymodbus
            slave_id: int = int(device_config["slave_id"])
            port: str = device_config["port"]
            device_type: str = device_config["type"]

            if port not in self.client_dict:
                client = AsyncModbusSerialClient(port=port, baudrate=9600, timeout=1)
                connected: bool = await client.connect()
                if not connected:
                    logger.warning(f"Failed to connect to port {port}")
                self.client_dict[port] = client

            # Use schema to get instance-level constraints
            instance_constraints: dict[str, ConstraintConfig] = ConfigManager.get_instance_constraints_from_schema(
                self.constraint_config_schema, model, slave_id
            )

            constraint_policy = ConstraintPolicy(instance_constraints, logger)

            # pass tables/modes into device; allow per-device override of modes in devices[].modes
            model_tables: dict = model_config.get("tables", {})
            model_modes: dict = model_config.get("modes", {})
            instance_modes_override: dict = device_config.get("modes", {})  # optional per-instance MV switch, etc.
            final_modes: dict = _deep_merge_dicts(model_modes, instance_modes_override)

            device = AsyncGenericModbusDevice(
                model=model,
                client=self.client_dict[port],
                slave_id=slave_id,
                register_type=model_config.get("register_type", "holding"),
                register_map=model_config["register_map"],
                constraint_policy=constraint_policy,
                device_type=device_type,
                table_dict=model_tables,
                mode_dict=final_modes,
                write_hooks=model_config.get("write_hooks", []),
            )
            self.device_list.append(device)

        # Apply startup frequencies after all devices are initialized
        await self._apply_startup_frequency()

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

    async def _apply_startup_frequency(self):
        """Set startup frequency for all devices"""
        if not self.constraint_config_schema:
            logger.warning("No constraint config available, skipping startup frequency setup")
            return

        logger.info("Applying startup frequencies to devices...")

        for device in self.device_list:
            startup_freq = ConfigManager._get_device_startup_frequency(
                self.constraint_config_schema, device.model, device.slave_id
            )

            if startup_freq is not None:
                await self._set_device_startup_frequency(device, startup_freq)
            else:
                logger.debug(f"[{device.model}_{device.slave_id}] No startup frequency configured")

    async def _set_device_startup_frequency(self, device: AsyncGenericModbusDevice, frequency: float):
        """Set the startup frequency for a single device"""
        device_id = f"{device.model}_{device.slave_id}"

        try:
            final_frequency = frequency

            # Check if correction is needed
            if not device.constraints.allow("RW_HZ", frequency):
                hz_constraint: ConstraintConfig | None = device.constraints.constraints.get("RW_HZ")
                if hz_constraint:
                    # Use the constraint minimum as the safe frequency
                    safe_freq = hz_constraint.min if hz_constraint.min is not None else frequency
                    logger.warning(
                        f"[{device_id}] Startup frequency {frequency} Hz outside constraints, "
                        f"using safe minimum value {safe_freq} Hz"
                    )
                    final_frequency = safe_freq

            await device.write_value("RW_HZ", final_frequency)
            logger.info(f"[{device_id}] Set startup frequency to {final_frequency} Hz")

        except Exception as e:
            logger.error(f"[{device_id}] Failed to set startup frequency: {e}")

    def _is_frequency_within_constraints(self, device: AsyncGenericModbusDevice, frequency: float) -> bool:
        """Check whether the frequency is within the device’s constraint range"""
        return device.constraints.allow("RW_HZ", frequency)
