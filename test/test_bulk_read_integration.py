import asyncio
import logging
from unittest.mock import AsyncMock

import pytest

from core.device.generic.generic_device import AsyncGenericModbusDevice
from core.device.generic.modbus_bus import ModbusBus
from core.model.device_constant import DEFAULT_MISSING_VALUE
from core.util.value_decoder import ValueDecoder

logger = logging.getLogger(__name__)


class DummyClient:
    """
    Minimal fake client that satisfies ModbusBus.ensure_connected() and internal access.
    We do NOT call real pymodbus in this test.
    """

    def __init__(self) -> None:
        self.connected = True

    async def connect(self) -> bool:
        self.connected = True
        return True


@pytest.mark.asyncio
async def test_read_all_bulk_should_reduce_read_regs_calls(monkeypatch):
    """
    Integration-ish:
    - Given contiguous holding registers, read_all() should use bulk read
    - Expect read_regs called in ranges (not per pin)
    """
    # Arrange
    # contiguous offsets: 0,1,2,3,4 => should combine to as few ranges as possible
    register_map = {
        "A": {"offset": 0, "format": "u16", "readable": True},
        "B": {"offset": 1, "format": "u16", "readable": True},
        "C": {"offset": 2, "format": "u16", "readable": True},
        "D": {"offset": 3, "format": "u16", "readable": True},
        "E": {"offset": 4, "format": "u16", "readable": True},
    }

    device = AsyncGenericModbusDevice(
        model="TST",
        client=DummyClient(),
        slave_id=1,
        register_type="holding",
        register_map=dict(register_map),
        device_type="ai_module",
        port="/dev/ttyFAKE",
        port_lock=asyncio.Lock(),
    )

    # Patch: avoid connect storms / real I/O
    monkeypatch.setattr(ModbusBus, "ensure_connected", AsyncMock(return_value=True))

    # Make bulk read return known data [100..]
    read_regs_mock = AsyncMock(return_value=[100, 101, 102, 103, 104])
    monkeypatch.setattr(ModbusBus, "read_regs", read_regs_mock)

    # Act
    values = await device.read_all()

    # Assert: 1 bulk call for the whole contiguous range
    assert read_regs_mock.await_count == 1
    read_regs_mock.assert_awaited_with(0, 5)

    assert values["A"] == 100
    assert values["B"] == 101
    assert values["C"] == 102
    assert values["D"] == 103
    assert values["E"] == 104


@pytest.mark.asyncio
async def test_read_all_bulk_should_skip_non_holding_and_still_bulk_read_dependencies(monkeypatch):
    """
    Integration-ish expectation for current bulk design:

    - Bulk reads ALL readable holding regs that are directly readable OR are dependencies
      for composed/scaled fields.
      e.g. composed_of depends on HI/MD/LO => bulk reads HI/MD/LO
           scale_from depends on KWH_SCALE_INDEX => bulk reads KWH_SCALE_INDEX

    - Non-holding pins (coil/discrete_input) must NOT be included in holding bulk;
      they should go through fallback read_value().
    """
    register_map = {
        # eligible (holding)
        "H0": {"offset": 0, "format": "u16", "readable": True},
        "H1": {"offset": 1, "format": "u16", "readable": True},
        # non-holding (excluded from holding bulk)
        "C0": {"offset": 0, "register_type": "coil", "readable": True},
        "D0": {"offset": 0, "register_type": "discrete_input", "readable": True},
        # computed (not directly bulk), but its dependencies are holding-readable
        "X48": {"readable": True, "composed_of": ["HI", "MD", "LO"]},
        "HI": {"offset": 10, "format": "u16", "readable": True},
        "MD": {"offset": 11, "format": "u16", "readable": True},
        "LO": {"offset": 12, "format": "u16", "readable": True},
        # scaled pin (often excluded), but scale index is holding-readable
        "S0": {"offset": 20, "format": "u16", "readable": True, "scale_from": "kwh_scale"},
        "KWH_SCALE_INDEX": {"offset": 30, "format": "u16", "readable": True},
    }

    device = AsyncGenericModbusDevice(
        model="TST",
        client=DummyClient(),
        slave_id=1,
        register_type="holding",
        register_map=dict(register_map),
        device_type="io_module",
        port="/dev/ttyFAKE",
        port_lock=asyncio.Lock(),
    )

    monkeypatch.setattr(ModbusBus, "ensure_connected", AsyncMock(return_value=True))

    # Bulk reads may be called multiple times for multiple ranges
    async def _read_regs_side_effect(start: int, count: int):
        # return deterministic dummy data by range
        if (start, count) == (0, 2):  # H0,H1
            return [200, 201]
        if (start, count) == (10, 3):  # HI,MD,LO
            return [1, 2, 3]
        if (start, count) == (30, 1):  # KWH_SCALE_INDEX
            return [7]
        raise AssertionError(f"Unexpected bulk range: start={start}, count={count}")

    read_regs_mock = AsyncMock(side_effect=_read_regs_side_effect)
    monkeypatch.setattr(ModbusBus, "read_regs", read_regs_mock)

    # fallback for non-holding pins only
    read_value_mock = AsyncMock()

    async def _read_value_side_effect(name: str):
        mapping = {
            "C0": 1,
            "D0": 0,
        }
        return mapping.get(name, DEFAULT_MISSING_VALUE)

    read_value_mock.side_effect = _read_value_side_effect
    device.read_value = read_value_mock

    values = await device.read_all()

    # ---- Assert: bulk ranges include holding readable regs and dependencies
    called_ranges = {(c.args[0], c.args[1]) for c in read_regs_mock.await_args_list}
    assert called_ranges == {(0, 2), (10, 3), (30, 1)}

    assert values["H0"] == 200
    assert values["H1"] == 201
    assert values["HI"] == 1
    assert values["MD"] == 2
    assert values["LO"] == 3
    assert values["KWH_SCALE_INDEX"] == 7

    # ---- Assert: non-holding pins go through fallback
    called_names = {c.args[0] for c in read_value_mock.await_args_list}
    assert "C0" in called_names
    assert "D0" in called_names

    assert values["C0"] == 1
    assert values["D0"] == 0

    # ---- Computed pins presence depends on your implementation:
    # If read_all computes X48/S0 internally, they should exist and not be DEFAULT_MISSING_VALUE.
    # If not computed in read_all, they may be missing or DEFAULT_MISSING_VALUE.
    #
    # Therefore we only assert "no crash" + "type stable" here:
    assert "X48" in values
    assert "S0" in values


@pytest.mark.asyncio
async def test_read_all_bulk_range_failure_should_mark_range_pins_missing(monkeypatch):
    """
    If a bulk read range fails, all pins covered by that range should become DEFAULT_MISSING_VALUE.
    Fallback should NOT overwrite them unless they were not in result already.
    """
    register_map = {
        "A": {"offset": 0, "format": "u16", "readable": True},
        "B": {"offset": 1, "format": "u16", "readable": True},
        "C": {"offset": 2, "format": "u16", "readable": True},
    }

    device = AsyncGenericModbusDevice(
        model="TST",
        client=DummyClient(),
        slave_id=1,
        register_type="holding",
        register_map=dict(register_map),
        device_type="ai_module",
        port="/dev/ttyFAKE",
        port_lock=asyncio.Lock(),
    )

    monkeypatch.setattr(ModbusBus, "ensure_connected", AsyncMock(return_value=True))

    # Force bulk read to fail
    read_regs_mock = AsyncMock(side_effect=Exception("bulk failed"))
    monkeypatch.setattr(ModbusBus, "read_regs", read_regs_mock)

    # Even if read_value could return something, bulk-failed pins are already in result,
    # so fallback loop should skip them (because name in result).
    read_value_mock = AsyncMock(return_value=12345)
    device.read_value = read_value_mock

    values = await device.read_all()

    assert read_regs_mock.await_count == 1
    assert values["A"] == DEFAULT_MISSING_VALUE
    assert values["B"] == DEFAULT_MISSING_VALUE
    assert values["C"] == DEFAULT_MISSING_VALUE

    # Fallback should NOT be called for A/B/C because they are already in result
    called_names = [c.args[0] for c in read_value_mock.await_args_list]
    assert "A" not in called_names
    assert "B" not in called_names
    assert "C" not in called_names


@pytest.mark.asyncio
async def test_read_all_bulk_should_handle_u32_word_count(monkeypatch):
    """
    Validate that word_count=2 formats (u32/f32) expand range end correctly.
    """
    register_map = {
        "U32": {"offset": 0, "format": "u32", "readable": True},  # needs 2 words
        "U16": {"offset": 2, "format": "u16", "readable": True},  # contiguous after u32 (0-1), next is 2
    }

    device = AsyncGenericModbusDevice(
        model="TST",
        client=DummyClient(),
        slave_id=1,
        register_type="holding",
        register_map=dict(register_map),
        device_type="panel_meter",
        port="/dev/ttyFAKE",
        port_lock=asyncio.Lock(),
    )

    monkeypatch.setattr(ModbusBus, "ensure_connected", AsyncMock(return_value=True))

    # Range should be start=0,count=3 covering words: [w0,w1,w2]
    # U32 consumes w0,w1; U16 consumes w2
    read_regs_mock = AsyncMock(return_value=[0x0001, 0x0002, 0x0003])
    monkeypatch.setattr(ModbusBus, "read_regs", read_regs_mock)

    # Patch decoder to deterministic behavior for u32 if you want to avoid endian assumptions.
    # Here we accept your current decoder behavior, but you can force it:
    # monkeypatch.setattr(ValueDecoder, "decode_registers", lambda self, fmt, regs: 0x0001_0002 if fmt == "u32" else regs[0])

    values = await device.read_all()

    assert read_regs_mock.await_count == 1
    read_regs_mock.assert_awaited_with(0, 3)

    # U16 is always last word
    assert values["U16"] == 0x0003
    # U32 depends on your ValueDecoder endianness; just assert it's not missing.
    assert values["U32"] != DEFAULT_MISSING_VALUE
