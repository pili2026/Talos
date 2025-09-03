from types import SimpleNamespace

import pytest

from device.generic.generic_device import AsyncGenericModbusDevice


class FakeClient:
    def __init__(self, registers: dict[int, int]):
        self._regs = registers
        self.connected = True

    async def connect(self):
        self.connected = True
        return True

    async def read_holding_registers(self, address, count, slave):
        vals = [self._regs.get(address + i, 0) for i in range(count)]
        return SimpleNamespace(registers=vals, isError=lambda: False)

    async def read_input_registers(self, address, count, slave):
        return await self.read_holding_registers(address, count, slave)

    async def write_register(self, address, value, slave):
        self._regs[address] = value
        return SimpleNamespace(isError=lambda: False)


@pytest.mark.asyncio
async def test_read_and_write_flow():
    regs = {0: 100, 1: 0, 2: 0, 10: 1}  # some defaults
    dev = AsyncGenericModbusDevice(
        model="TEST",
        client=FakeClient(regs),
        slave_id=1,
        register_type="holding",
        register_map={
            "VAL": {"offset": 0, "readable": True, "writable": True, "format": "u16", "scale": 0.1},
            "RW_ON_OFF": {"offset": 10, "readable": True, "writable": True, "format": "u16"},
        },
        device_type="inverter",
    )

    # read with scale 0.1 → 100 * 0.1 = 10.0
    v = await dev.read_value("VAL")
    assert v == pytest.approx(10.0)

    # write_on_off
    await dev.write_on_off(0)
    assert regs[10] == 0

    # write_value with scale 0.1 → raw = round(12.3 / 0.1) = 123
    await dev.write_value("VAL", 12.3)
    assert regs[0] == 123
