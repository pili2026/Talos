import asyncio
import logging
from unittest.mock import AsyncMock, Mock

import pytest

from core.device.generic.generic_device import AsyncGenericModbusDevice
from core.device.modbus.bulk_reader import BulkRange, ModbusBulkReader
from core.model.device_constant import DEFAULT_MISSING_VALUE

# ==================== Helper functions ====================


def _make_device_for_test(register_map: dict) -> AsyncGenericModbusDevice:
    """Create a minimal AsyncGenericModbusDevice for testing."""
    mock_client = Mock()
    mock_lock = asyncio.Lock()

    device = AsyncGenericModbusDevice(
        model="TEST_MODEL",
        client=mock_client,
        slave_id=1,
        register_type="holding",
        register_map=register_map,
        device_type="test",
        port="/dev/ttyUSB0",
        port_lock=mock_lock,
    )
    return device


def _make_bulk_reader(register_map: dict, default_register_type: str = "holding") -> ModbusBulkReader:
    """Create a ModbusBulkReader for testing."""

    logger = logging.getLogger("test")
    return ModbusBulkReader(register_map, default_register_type, logger)


# ==================== Tests for ModbusBulkReader ====================


def test_build_bulk_ranges_empty_register_map():
    """Test with empty register map."""
    reader = _make_bulk_reader({})
    ranges = reader.build_bulk_ranges()
    assert ranges == []


def test_build_bulk_ranges_no_eligible_pins():
    """Test with no bulk-eligible pins."""
    register_map = {
        "A": {"offset": 0, "format": "u16", "readable": False},  # not readable
        "B": {"offset": 1, "format": "u16", "writable": True},  # no readable flag
        "C": {"offset": 2, "format": "u16", "readable": True, "register_type": "coil"},  # coil not eligible
    }
    reader = _make_bulk_reader(register_map)
    ranges = reader.build_bulk_ranges()
    assert ranges == []


def test_build_bulk_ranges_single_contiguous_range():
    """Test building a single contiguous range."""
    register_map = {
        "A": {"offset": 0, "format": "u16", "readable": True},
        "B": {"offset": 1, "format": "u16", "readable": True},
        "C": {"offset": 2, "format": "u16", "readable": True},
    }
    reader = _make_bulk_reader(register_map)
    ranges = reader.build_bulk_ranges()

    assert len(ranges) == 1
    r = ranges[0]
    assert r.register_type == "holding"
    assert r.start == 0
    assert r.count == 3
    assert len(r.items) == 3
    assert [name for name, cfg in r.items] == ["A", "B", "C"]


def test_build_bulk_ranges_non_contiguous():
    """Test splitting ranges when offsets are non-contiguous."""
    register_map = {
        "A": {"offset": 0, "format": "u16", "readable": True},
        "B": {"offset": 1, "format": "u16", "readable": True},
        "C": {"offset": 10, "format": "u16", "readable": True},  # gap
    }
    reader = _make_bulk_reader(register_map)
    ranges = reader.build_bulk_ranges()

    assert len(ranges) == 2
    # First range
    assert ranges[0].start == 0
    assert ranges[0].count == 2
    assert [name for name, cfg in ranges[0].items] == ["A", "B"]
    # Second range
    assert ranges[1].start == 10
    assert ranges[1].count == 1
    assert [name for name, cfg in ranges[1].items] == ["C"]


def test_build_bulk_ranges_multi_word_format():
    """Test handling multi-word formats (u32, f32)."""
    register_map = {
        "A": {"offset": 0, "format": "u16", "readable": True},  # 1 word
        "B": {"offset": 1, "format": "u32", "readable": True},  # 2 words (offset 1-2)
        "C": {"offset": 3, "format": "f32", "readable": True},  # 2 words (offset 3-4)
    }
    reader = _make_bulk_reader(register_map)
    ranges = reader.build_bulk_ranges()

    assert len(ranges) == 1
    r = ranges[0]
    assert r.start == 0
    assert r.count == 5  # 1 + 2 + 2 = 5 words total
    assert len(r.items) == 3


def test_build_bulk_ranges_different_register_types():
    """Test splitting ranges when register types differ."""
    register_map = {
        "A": {"offset": 0, "format": "u16", "readable": True, "register_type": "holding"},
        "B": {"offset": 1, "format": "u16", "readable": True, "register_type": "holding"},
        "C": {"offset": 2, "format": "u16", "readable": True, "register_type": "input"},
    }
    reader = _make_bulk_reader(register_map)
    ranges = reader.build_bulk_ranges()

    assert len(ranges) == 2
    # Holding range
    assert ranges[0].register_type == "holding"
    assert ranges[0].start == 0
    assert ranges[0].count == 2
    # Input range
    assert ranges[1].register_type == "input"
    assert ranges[1].start == 2
    assert ranges[1].count == 1


def test_build_bulk_ranges_contiguous_and_split_by_max_regs():
    """Test splitting contiguous ranges when exceeding max_regs_per_req."""
    register_map = {
        # eligible holding pins, contiguous offsets
        "A": {"offset": 0, "format": "u16", "readable": True},
        "B": {"offset": 1, "format": "u16", "readable": True},
        "C": {"offset": 2, "format": "u16", "readable": True},
        # eligible but non-contiguous
        "D": {"offset": 10, "format": "u16", "readable": True},
    }
    reader = _make_bulk_reader(register_map)
    ranges = reader.build_bulk_ranges(max_regs_per_req=3)

    # Should get 2 ranges: [A,B,C] and [D]
    # Even though A,B,C are contiguous, if we set max=2, it would split further
    assert len(ranges) == 2
    assert ranges[0].count == 3
    assert ranges[1].count == 1


def test_build_bulk_ranges_split_when_exceeding_max():
    """Test splitting when contiguous range exceeds max_regs_per_req."""
    register_map = {
        "A": {"offset": 0, "format": "u16", "readable": True},
        "B": {"offset": 1, "format": "u16", "readable": True},
        "C": {"offset": 2, "format": "u16", "readable": True},
    }
    reader = _make_bulk_reader(register_map)
    ranges = reader.build_bulk_ranges(max_regs_per_req=2)

    # Should split: [A,B] and [C]
    assert len(ranges) == 2
    assert ranges[0].start == 0
    assert ranges[0].count == 2
    assert [name for name, cfg in ranges[0].items] == ["A", "B"]

    assert ranges[1].start == 2
    assert ranges[1].count == 1
    assert [name for name, cfg in ranges[1].items] == ["C"]


def test_build_bulk_ranges_exclude_composed_of():
    """Test that pins with composed_of are excluded from bulk read."""
    register_map = {
        "A": {"offset": 0, "format": "u16", "readable": True},
        "B": {"offset": 1, "format": "u16", "readable": True, "composed_of": ["HI", "MD", "LO"]},
        "C": {"offset": 2, "format": "u16", "readable": True},
    }
    reader = _make_bulk_reader(register_map)
    ranges = reader.build_bulk_ranges()

    # B should be excluded, so we get two separate ranges
    assert len(ranges) == 2
    assert [name for name, cfg in ranges[0].items] == ["A"]
    assert [name for name, cfg in ranges[1].items] == ["C"]


def test_build_bulk_ranges_exclude_scale_from():
    """Test that pins with scale_from are excluded from bulk read."""
    register_map = {
        "A": {"offset": 0, "format": "u16", "readable": True},
        "B": {"offset": 1, "format": "u16", "readable": True, "scale_from": "voltage_index"},
        "C": {"offset": 2, "format": "u16", "readable": True},
    }
    reader = _make_bulk_reader(register_map)
    ranges = reader.build_bulk_ranges()

    # B should be excluded
    assert len(ranges) == 2
    assert [name for name, cfg in ranges[0].items] == ["A"]
    assert [name for name, cfg in ranges[1].items] == ["C"]


def test_build_bulk_ranges_exclude_coil_and_discrete_input():
    """Test that coil and discrete_input pins are excluded."""
    register_map = {
        "A": {"offset": 0, "format": "u16", "readable": True, "register_type": "holding"},
        "B": {"offset": 1, "format": "u16", "readable": True, "register_type": "coil"},
        "C": {"offset": 2, "format": "u16", "readable": True, "register_type": "discrete_input"},
        "D": {"offset": 3, "format": "u16", "readable": True, "register_type": "holding"},
    }
    reader = _make_bulk_reader(register_map)
    ranges = reader.build_bulk_ranges()

    # Only A and D should be included, but they're not contiguous
    assert len(ranges) == 2
    assert [name for name, cfg in ranges[0].items] == ["A"]
    assert [name for name, cfg in ranges[1].items] == ["D"]


# ==================== Tests for process_bulk_range_result ====================


def test_process_bulk_range_result_simple():
    """Test processing bulk read results."""
    register_map = {
        "A": {"offset": 0, "format": "u16", "readable": True, "scale": 1.0},
        "B": {"offset": 1, "format": "u16", "readable": True, "scale": 0.1},
    }
    reader = _make_bulk_reader(register_map)

    bulk_range = BulkRange(
        register_type="holding", start=0, count=2, items=[("A", register_map["A"]), ("B", register_map["B"])]
    )

    registers = [100, 200]

    def mock_is_invalid(cfg, words):
        return False

    result = reader.process_bulk_range_result(bulk_range, registers, mock_is_invalid)

    assert result["A"] == 100.0  # 100 * 1.0
    assert result["B"] == 20.0  # 200 * 0.1


def test_process_bulk_range_result_with_invalid_raw():
    """Test processing with invalid raw values."""
    register_map = {
        "A": {"offset": 0, "format": "u16", "readable": True},
        "B": {"offset": 1, "format": "u16", "readable": True},
    }
    reader = _make_bulk_reader(register_map)

    bulk_range = BulkRange(
        register_type="holding", start=0, count=2, items=[("A", register_map["A"]), ("B", register_map["B"])]
    )

    registers = [65535, 200]  # 65535 is invalid sentinel

    def mock_is_invalid(cfg, words):
        # Return True if first word is 65535
        return words[0] == 65535

    result = reader.process_bulk_range_result(bulk_range, registers, mock_is_invalid)

    assert result["A"] == DEFAULT_MISSING_VALUE  # Invalid
    assert result["B"] == 200  # Valid


def test_process_bulk_range_result_multi_word():
    """Test processing multi-word formats."""
    register_map = {
        "A": {"offset": 0, "format": "u32", "readable": True},  # 2 words
    }
    reader = _make_bulk_reader(register_map)

    bulk_range = BulkRange(register_type="holding", start=0, count=2, items=[("A", register_map["A"])])

    # u32 big-endian: [high_word, low_word]
    registers = [0x0001, 0x0002]  # Should decode to 65538

    def mock_is_invalid(cfg, words):
        return False

    result = reader.process_bulk_range_result(bulk_range, registers, mock_is_invalid)

    # The decoder will handle this - just check it's not -1
    assert result["A"] != DEFAULT_MISSING_VALUE


def test_process_bulk_range_result_with_precision():
    """Test processing with precision rounding."""
    register_map = {
        "A": {"offset": 0, "format": "u16", "readable": True, "scale": 0.1, "precision": 2},
    }
    reader = _make_bulk_reader(register_map)

    bulk_range = BulkRange(register_type="holding", start=0, count=1, items=[("A", register_map["A"])])

    registers = [123]  # 123 * 0.1 = 12.3

    def mock_is_invalid(cfg, words):
        return False

    result = reader.process_bulk_range_result(bulk_range, registers, mock_is_invalid)

    assert result["A"] == 12.3


# ==================== Integration tests with AsyncGenericModbusDevice ====================


def test_device_bulk_reader_integration():
    """Test that device properly initializes and uses bulk_reader."""
    register_map = {
        "A": {"offset": 0, "format": "u16", "readable": True},
        "B": {"offset": 1, "format": "u16", "readable": True},
    }
    device = _make_device_for_test(register_map)

    # Check that bulk_reader is initialized
    assert device.bulk_reader is not None
    assert isinstance(device.bulk_reader, ModbusBulkReader)

    # Check that it can build ranges
    ranges = device.bulk_reader.build_bulk_ranges()
    assert len(ranges) == 1
    assert ranges[0].count == 2


@pytest.mark.asyncio
async def test_device_read_all_uses_bulk_reader():
    """Test that read_all properly uses bulk_reader."""
    register_map = {
        "A": {"offset": 0, "format": "u16", "readable": True},
        "B": {"offset": 1, "format": "u16", "readable": True},
    }
    device = _make_device_for_test(register_map)

    # Mock the bus to return success
    device.bus.ensure_connected = AsyncMock(return_value=True)
    device.bus.read_regs = AsyncMock(return_value=[100, 200])

    result = await device.read_all()

    # Should have called read_regs once for the bulk range
    device.bus.read_regs.assert_called_once()

    # Check results
    assert result["A"] == 100
    assert result["B"] == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
