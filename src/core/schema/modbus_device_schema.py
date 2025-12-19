from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)


class ModbusBusConfig(BaseModel):
    """
    One RTU bus (serial port settings).
    """

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    port: str = Field(..., description="Serial port path (e.g., /dev/ttyUSB0)")
    baudrate: int = Field(default=9600, description="Baud rate")
    timeout: float = Field(default=1.0, gt=0, le=2.0, description="Modbus client timeout for this bus (seconds)")

    @field_validator("baudrate", mode="before")
    @classmethod
    def _to_int_baudrate(cls, v: Any) -> int:
        try:
            return int(v)
        except Exception:
            fallback_baudrate: int = 9600
            logger.warning(f"[modbus_device] invalid baudrate={v!r}, fallback={fallback_baudrate}")
            return fallback_baudrate

    @field_validator("timeout", mode="before")
    @classmethod
    def _to_float_timeout(cls, v: Any) -> float:
        try:
            return float(v)
        except Exception:
            fallback_timeout: float = 1.0
            logger.warning(f"[modbus_device] invalid timeout={v!r}, fallback={fallback_timeout}")
            return fallback_timeout


class ModbusDeviceConfig(BaseModel):
    """
    One device instance row in `devices:`.
    Supports either:
      - YAML anchor merge (device already contains port/baudrate/timeout), OR
      - bus reference via `bus: rtu0` (optional; if you want it).
    """

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    model: str
    type: str
    model_file: str

    slave_id: int

    # Either provided by YAML merge, or resolved from buses via `bus`
    port: str | None = None
    baudrate: int | None = None
    timeout: float | None = None

    modes: dict[str, Any] = Field(default_factory=dict)

    bus: str | None = None

    @field_validator("slave_id", mode="before")
    @classmethod
    def _to_int_slave_id(cls, v: Any) -> int:
        try:
            return int(v)
        except Exception:
            logger.warning(f"[modbus_device] invalid slave_id={v!r}, fallback=0")
            return 0

    @field_validator("baudrate", mode="before")
    @classmethod
    def _to_int_baudrate(cls, v: Any) -> int | None:
        if v is None:
            return None
        try:
            return int(v)
        except Exception:
            logger.warning(f"[modbus_device] invalid device baudrate={v!r}, fallback=None")
            return None

    @field_validator("timeout", mode="before")
    @classmethod
    def _to_float_timeout(cls, v: Any) -> float | None:
        if v is None:
            return None
        try:
            return float(v)
        except Exception:
            logger.warning(f"[modbus_device] invalid device timeout={v!r}, fallback=None")
            return None


class ModbusDeviceFileConfig(BaseModel):
    """
    Root config for modbus_device.yml
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, populate_by_name=True)

    bus_dict: dict[str, ModbusBusConfig] = Field(default_factory=dict, validation_alias="buses")
    device_list: list[ModbusDeviceConfig] = Field(default_factory=list, validation_alias="devices")

    # ---- Derived / helper API ----

    def resolve_device_bus_settings(self) -> list[ModbusDeviceConfig]:
        """
        Ensure each device has (port, baudrate, timeout).
        Priority:
          1) device explicit fields (after YAML merge)
          2) device.bus reference -> buses[bus]
          3) safe fallback (port is required; if missing, keep None and let caller decide to skip)
        """
        resolved: list[ModbusDeviceConfig] = []
        for device in self.device_list:
            # Already has port from YAML merge
            if device.port:
                if device.baudrate is None:
                    device.baudrate = 9600
                if device.timeout is None:
                    device.timeout = 1.0
                resolved.append(device)
                continue

            # Use bus reference if provided
            if device.bus:
                bus = self.bus_dict.get(device.bus)
                if not bus:
                    logger.warning(
                        f"[modbus_device] unknown bus={device.bus!r} for device {device.model}_{device.slave_id}"
                    )
                    resolved.append(device)
                    continue
                device.port = bus.port
                device.baudrate = int(device.baudrate or bus.baudrate)
                device.timeout = float(device.timeout or bus.timeout)
                resolved.append(device)
                continue

            # No port and no bus reference
            logger.warning(f"[modbus_device] device missing port/bus: {device.model}_{device.slave_id}")
            resolved.append(device)

        return resolved
