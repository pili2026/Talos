import logging
from typing import Any, Dict

from pymodbus.client import AsyncModbusSerialClient
from pymodbus.exceptions import ModbusException


class AsyncGenericModbusDevice:
    def __init__(
        self,
        device_id: str,
        client: AsyncModbusSerialClient,
        slave_id: int,
        register_type: str,
        pins: dict,
        model: str,
    ):
        self.device_id = device_id
        self.client = client
        self.slave_id = slave_id
        self.register_type = register_type
        self.pins = pins
        self.model = model or device_id
        self.logger = logging.getLogger(f"Device.{self.model}")

    async def read_all(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for name, config in self.pins.items():
            if not config.get("readable", False):
                continue
            try:
                value = await self._read_value(name, config)
                result[name] = value
            except Exception as e:
                self.logger.warning(f"Failed to read {name}: {e}")
        return result

    async def _read_value(self, name: str, config: dict) -> float | int:
        offset = config["offset"]
        bit = config.get("bit")
        scale = config.get("scale", 1.0)
        formula = config.get("formula")
        combine_high = config.get("combine_high")
        combine_scale = config.get("combine_scale", 1.0)

        if combine_high:
            low = await self._read_register(offset)
            high = await self._read_register(combine_high)
            combined = high * 65536 + low
            return combined / combine_scale

        raw = await self._read_register(offset)

        if bit is not None:
            return (raw >> bit) & 1

        if formula:
            n1, n2, n3 = formula
            return (raw + n1) * n2 + n3
        else:
            return raw * scale

    async def _read_register(self, address: int) -> int:
        if not self.client.connected:
            connected = await self.client.connect()
            if not connected:
                raise ModbusException(f"Failed to connect [{self.client}]")

        if self.register_type == "holding":
            resp = await self.client.read_holding_registers(address=address, count=1, slave=self.slave_id)
        elif self.register_type == "input":
            resp = await self.client.read_input_registers(address=address, count=1, slave=self.slave_id)
        else:
            raise ValueError(f"Unsupported register type: {self.register_type}")

        if resp.isError():
            raise ModbusException(f"Read error: {resp}")

        return int(resp.registers[0])
