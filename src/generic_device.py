import logging
from typing import Any, Dict

from pymodbus.client import AsyncModbusSerialClient
from pymodbus.exceptions import ModbusException

from util.decode_util import NumericFormat, decode_numeric_by_format


class AsyncGenericModbusDevice:
    def __init__(
        self,
        model: str,
        client: AsyncModbusSerialClient,
        slave_id: int,
        register_type: str,
        register_map: dict,
        device_type: str,
        constraints: dict = None,
    ):
        self.model = model
        self.client = client
        self.slave_id = slave_id
        self.register_type = register_type
        self.register_map = register_map
        self.logger = logging.getLogger(f"Device.{self.model}")
        self.device_type = device_type
        self.constraints = constraints or {}

        self.output_register_map = [k for k, v in register_map.items() if v.get("writable")]

    @property
    def pin_type_map(self) -> dict[str, str]:
        """
        Converts pins with a defined 'type' in the register_map to their corresponding
        unified sensor type.
        Pins without a defined 'type' will not appear in the result.
        """
        type_mapping = {
            "thermometer": "Temp",
            "pressure": "Pressure",
            # Extendable mapping for more driver-defined types
        }

        return {
            pin: type_mapping[cfg["type"]]
            for pin, cfg in self.register_map.items()
            if "type" in cfg and cfg["type"] in type_mapping
        }

    async def read_all(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for name, config in self.register_map.items():
            if not config.get("readable", False):
                continue
            try:
                value = await self._read_value(config)
                result[name] = value
            except Exception as e:
                self.logger.warning(f"Failed to read {name}: {e}")
        return result

    async def read_value(self, name: str) -> float | int:
        cfg: dict = self.register_map.get(name)
        if not cfg or not cfg.get("readable"):
            raise ValueError(f"[{self.model}] register_map {name} is not readable")
        return await self._read_value(cfg)

    async def write_value(self, name: str, value: int | float):
        cfg: dict = self._validate_writable(name)

        if not self._validate_constraints(name, value):
            return

        raw: int = self._scale_to_raw(value, cfg.get("scale", 1.0))

        await self._write_register(cfg["offset"], raw)
        self.logger.info(f"[{self.model}] Write {value} ({raw}) to {name} (offset={cfg['offset']})")

    async def _read_value(self, config: dict) -> float | int:
        # Read register based on configuration
        if config.get("combine_high") is not None:
            result = await self._read_combined_registers(config)
        else:
            result = await self._read_formatted_register(config)

        # Bitmask application
        if config.get("bit") is not None:
            return self._apply_bitmask(result, config["bit"])

        # Formula application
        if config.get("formula"):
            return self._apply_formula(result, config["formula"])

        # Scale application
        return self._apply_scale(result, config.get("scale", 1.0))

    async def _read_register(self, address: int) -> int:
        result = await self._read_registers(address, 1)
        return result[0]

    async def _read_registers(self, address: int, count: int) -> list[int]:
        if not self.client.connected:
            connected: bool = await self.client.connect()
            if not connected:
                raise ModbusException(f"Failed to connect [{self.client}]")

        if self.register_type == "holding":
            resp = await self.client.read_holding_registers(address=address, count=count, slave=self.slave_id)
        elif self.register_type == "input":
            resp = await self.client.read_input_registers(address=address, count=count, slave=self.slave_id)
        else:
            raise ValueError(f"Unsupported register type: {self.register_type}")

        if resp.isError():
            raise ModbusException(f"Read error: {resp}")

        return resp.registers

    async def _write_register(self, address: int, value: int):
        self.logger.info(f"[{self.model}] Write raw value {value} to offset {address}")
        await self.client.write_register(address=address, value=value, slave=self.slave_id)

    async def write_on_off(self, value: int):
        """Control the on/off state of the device."""

        reg_name = "RW_ON_OFF"  # TODO: Use Enum or constant for register name
        cfg: dict = self.register_map.get(reg_name)

        if not cfg or not cfg.get("writable"):
            raise ValueError(f"[{self.model}] {reg_name} is not writable or not defined")

        await self.write_value(reg_name, value)
        self.logger.info(f"[{self.model}] Write {value} to {reg_name} (offset={cfg['offset']})")

    async def _read_combined_registers(self, config: dict) -> float:
        low: int = await self._read_register(config["offset"])
        high: int = await self._read_register(config["combine_high"])
        combined: int = (high << 16) + low
        return combined / config.get("combine_scale", 1.0)

    async def _read_formatted_register(self, config: dict) -> float | int:
        count = 2 if config.get("format", "uint16") in {NumericFormat.FLOAT32, NumericFormat.UINT32} else 1
        raw: list[int] = await self._read_registers(config["offset"], count)
        return decode_numeric_by_format(raw, config.get("format", "uint16"))

    def _validate_writable(self, name: str) -> dict:
        cfg: dict = self.register_map.get(name)
        if not cfg or not cfg.get("writable"):
            raise ValueError(f"[{self.model}] register_map {name} is not writable")
        return cfg

    def _validate_constraints(self, name: str, value: int | float) -> bool:
        if name in self.constraints:
            limit = self.constraints[name]
            min_val = limit.get("min", 60.0)
            max_val = limit.get("max", 60.0)
            if not min_val <= value <= max_val:
                self.logger.warning(f"[{self.model}] Reject write: {name}={value} out of range [{min_val}, {max_val}]")
                return False
        return True

    @staticmethod
    def _scale_to_raw(value: int | float, scale: float) -> int:
        return int(round(value / scale))

    @staticmethod
    def _apply_bitmask(value: float | int, bit: int) -> int:
        return (int(value) >> bit) & 1

    @staticmethod
    def _apply_formula(value: float | int, formula: tuple) -> float:
        n1, n2, n3 = formula
        return (value + n1) * n2 + n3

    @staticmethod
    def _apply_scale(value: float | int, scale: float) -> float:
        return value * scale
