import logging
from abc import ABC, abstractmethod
from typing import Any


class BaseDevice(ABC):
    """Base class for all device types (Modbus, MQTT, HTTP, etc.)"""

    def __init__(self, model: str, slave_id: int | str, device_type: str, register_map: dict):
        self.model = model
        self.slave_id = slave_id
        self.device_type = device_type
        self.register_map = register_map
        self.logger = logging.getLogger(f"Device.{self.model}")

    # ==================== Abstract methods ====================

    @abstractmethod
    async def read_value(self, name: str) -> float | int:
        """Read a single parameter value."""
        pass

    @abstractmethod
    async def write_value(self, name: str, value: int | float) -> None:
        """Write a value to a parameter."""
        pass

    @abstractmethod
    async def read_all(self) -> dict[str, Any]:
        """Read all parameters as a snapshot."""
        pass

    # ==================== Concrete methods ====================

    def get_control_register(self) -> str | None:
        """
        Find first writable on/off control register.

        Priority: RW_ON_OFF > RW_RUN > RW_START_STOP > RW_START > RW_STOP
        """
        candidates = ["RW_ON_OFF", "RW_RUN", "RW_START_STOP", "RW_START", "RW_STOP"]

        for key in candidates:
            reg_config: dict = self.register_map.get(key)
            if reg_config and reg_config.get("writable", True):
                return key

        return None

    async def is_running(self) -> bool:
        """
        Check if device is currently ON/running.

        Returns:
            True if device is ON, False otherwise or if control register not found.
        """
        control_reg: str | None = self.get_control_register()
        if not control_reg:
            return False

        try:
            value = await self.read_value(control_reg)
            return value == 1
        except Exception as exc:
            self.logger.warning(f"[{self.model}_{self.slave_id}] is_running check failed: {exc}")
            return False

    async def turn_on(self) -> bool:
        """
        Turn on the device.

        Returns:
            True if successful, False otherwise.
        """
        control_reg: str | None = self.get_control_register()
        if not control_reg:
            self.logger.warning(f"[{self.model}_{self.slave_id}] No control register found")
            return False

        try:
            await self.write_value(control_reg, 1)
            self.logger.info(f"[{self.model}_{self.slave_id}] Turned ON ({control_reg}=1)")
            return True
        except Exception as exc:
            self.logger.error(f"[{self.model}_{self.slave_id}] turn_on failed: {exc}")
            return False

    async def turn_off(self) -> bool:
        """
        Turn off the device.

        Returns:
            True if successful, False otherwise.
        """
        control_reg: str | None = self.get_control_register()
        if not control_reg:
            self.logger.warning(f"[{self.model}_{self.slave_id}] No control register found")
            return False

        try:
            await self.write_value(control_reg, 0)
            self.logger.info(f"[{self.model}_{self.slave_id}] Turned OFF ({control_reg}=0)")
            return True
        except Exception as exc:
            self.logger.error(f"[{self.model}_{self.slave_id}] turn_off failed: {exc}")
            return False

    def supports_control(self) -> bool:
        """Check if device supports on/off control."""
        return self.get_control_register() is not None

    def supports_on_off(self) -> bool:
        """Legacy method - alias for supports_control()."""
        return self.supports_control()

    @property
    def pin_type_map(self) -> dict[str, str]:
        """
        Map pin names to their types (Temp, Pressure, etc.).

        Returns:
            Dict mapping pin name to type string.
        """
        type_mapping = {"thermometer": "Temp", "pressure": "Pressure"}
        return {
            pin: type_mapping[cfg["type"]]
            for pin, cfg in self.register_map.items()
            if "type" in cfg and cfg["type"] in type_mapping
        }

    def get_health_check_config(self) -> dict | None:
        """
        Get health check configuration from device model definition.

        Returns:
            Health check config dict if defined, None otherwise.
        """
        return None
