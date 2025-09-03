from pymodbus.client import AsyncModbusSerialClient
from pymodbus.exceptions import ModbusException


class ModbusBus:
    def __init__(self, client: AsyncModbusSerialClient, slave_id: int, register_type: str):
        self.client = client
        self.slave_id = int(slave_id)
        self.register_type = register_type

    async def read_u16(self, offset: int) -> int:
        regs = await self.read_regs(offset, 1)
        return int(regs[0])

    async def read_regs(self, offset: int, count: int) -> list[int]:
        if not self.client.connected and not await self.client.connect():
            raise ModbusException("connect failed")
        if self.register_type == "holding":
            resp = await self.client.read_holding_registers(address=offset, count=count, slave=self.slave_id)
        elif self.register_type == "input":
            resp = await self.client.read_input_registers(address=offset, count=count, slave=self.slave_id)
        else:
            raise ValueError(f"Unsupported register type: {self.register_type}")

        if resp.isError():
            raise ModbusException(str(resp))
        return resp.registers

    async def write_u16(self, offset: int, value: int):
        await self.client.write_register(address=offset, value=value, slave=self.slave_id)
