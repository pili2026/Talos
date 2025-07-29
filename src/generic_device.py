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
    ):
        self.model = model
        self.client = client
        self.slave_id = slave_id
        self.register_type = register_type
        self.register_map = register_map
        self.logger = logging.getLogger(f"Device.{self.model}")

        self.output_register_map = [k for k, v in register_map.items() if v.get("writable")]

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
        cfg: dict = self.register_map.get(name)
        if not cfg or not cfg.get("writable"):
            raise ValueError(f"[{self.model}] register_map {name} is not writable")

        offset = cfg["offset"]
        scale = cfg.get("scale", 1.0)
        raw = int(value / scale)

        await self._write_register(offset, raw)
        self.logger.info(f"[{self.model}] Write {value} ({raw}) to {name} (offset={offset})")

    async def _read_value(self, config: dict) -> float | int:
        offset = config["offset"]
        scale = config.get("scale", 1.0)
        formula = config.get("formula")
        bit = config.get("bit")
        combine_high = config.get("combine_high")
        combine_scale = config.get("combine_scale", 1.0)
        fmt = config.get("format", "uint16")

        # Combine two registers manually if specified
        if combine_high is not None:
            low = await self._read_register(offset)
            high = await self._read_register(combine_high)
            combined = high * 65536 + low
            result = combined / combine_scale
        else:
            # Decode using specified format
            raw = await self._read_registers(offset, 2 if fmt in {NumericFormat.FLOAT32, NumericFormat.UINT32} else 1)
            result = decode_numeric_by_format(raw, fmt)

        # Apply bit mask if needed (for digital signals)
        if bit is not None:
            return (int(result) >> bit) & 1

        # Apply formula if defined
        if formula:
            n1, n2, n3 = formula
            return (result + n1) * n2 + n3

        # Apply scale if defined
        return result * scale

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
