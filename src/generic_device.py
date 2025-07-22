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
        address: dict,
        model: str,
    ):
        self.device_id = device_id
        self.client = client
        self.slave_id = slave_id
        self.register_type = register_type
        self.address = address
        self.model = model or device_id
        self.logger = logging.getLogger(f"Device.{self.model}")

        self.output_pins = [k for k, v in address.items() if v.get("writable")]

    async def read_all(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for name, config in self.address.items():
            if not config.get("readable", False):
                continue
            try:
                value = await self._read_value(config)
                result[name] = value
            except Exception as e:
                self.logger.warning(f"Failed to read {name}: {e}")
        return result

    async def set_frequency(self, value: float):
        address_cfg: dict = self.address.get("RW_HZ")
        if not address_cfg or not address_cfg.get("writable"):
            raise ValueError("Device does not support frequency control")
        offset = address_cfg["offset"]
        scale = address_cfg.get("scale", 1.0)
        raw_value = int(value / scale)
        await self._write_register(offset, raw_value)

    async def write_do(self, address: str, value: int):
        address_cfg: dict = self.address.get(address)
        if not address_cfg or not address_cfg.get("writable"):
            raise ValueError(f"Address {address} is not writable")
        offset = address_cfg["offset"]
        await self._write_register(offset, value)

    async def _read_value(self, config: dict) -> float | int:
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

    async def _write_register(self, address: int, value: int):
        self.logger.info(f"[{self.device_id}] Write {value} to offset {address}")
        await self.client.write_register(address=address, value=value, slave=self.slave_id)
