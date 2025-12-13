import pytest

from core.device.generic.generic_device import AsyncGenericModbusDevice, BulkRange
from core.model.device_constant import DEFAULT_MISSING_VALUE
from core.util.value_decoder import ValueDecoder

pytestmark = pytest.mark.asyncio


class FakeComputedFieldProcessor:
    """Stub: keep interface used by read_all()."""

    def __init__(self, register_map: dict):
        self._register_map = register_map
        self._enabled = True

    def has_computed_fields(self) -> bool:
        return self._enabled

    def compute(self, values: dict):
        # example: add computed field if inputs exist
        if (
            "A" in values
            and "B" in values
            and values["A"] != DEFAULT_MISSING_VALUE
            and values["B"] != DEFAULT_MISSING_VALUE
        ):
            values["A_plus_B"] = values["A"] + values["B"]
        return values


class FakeScaleService:
    async def get_factor(self, kind: str, index_reader):
        return 1.0


class FakeHookManager:
    def on_write(self, name: str, cfg: dict):
        return None


class FakeBus:
    """
    Fake ModbusBus for unit tests.
    It supports:
      - ensure_connected()
      - read_regs(start, count)
    """

    def __init__(self, *, connected=True, regs_by_range=None, raise_on=None):
        self._connected = connected
        self._regs_by_range = regs_by_range or {}  # {(start,count): [regs...]}
        self._raise_on = set(raise_on or [])  # {(start,count)}

    async def ensure_connected(self) -> bool:
        return bool(self._connected)

    async def read_regs(self, start: int, count: int):
        key = (int(start), int(count))
        if key in self._raise_on:
            raise TimeoutError(f"fake bulk read timeout: {key}")
        if key not in self._regs_by_range:
            # Simulate device returned insufficient data
            return [DEFAULT_MISSING_VALUE] * count
        return list(self._regs_by_range[key])


def _make_device_for_test(register_map: dict):
    """
    Build AsyncGenericModbusDevice without hitting real pymodbus client.
    We instantiate and then patch internal collaborators (bus, scales, hooks, computed).
    """
    # client can be None because we won't use it after we patch bus
    device = AsyncGenericModbusDevice(
        model="TEST_MODEL",
        client=None,  # patched
        slave_id=1,
        register_type="holding",
        register_map=dict(register_map),
        device_type="test_device",
        port="/dev/null",
        port_lock=None,
        table_dict={},
        mode_dict={},
        write_hooks=[],
        constraint_policy=None,
    )

    # Patch collaborators to avoid depending on their real implementations
    device.scales = FakeScaleService()
    device.hooks = FakeHookManager()
    device.decoder = ValueDecoder()

    # Patch computed processor
    device.computed_processor = FakeComputedFieldProcessor(device.register_map)
    return device


def test_build_bulk_ranges_contiguous_and_split_by_max_regs():
    register_map = {
        # eligible holding pins, contiguous offsets
        "A": {"offset": 0, "format": "u16", "readable": True},
        "B": {"offset": 1, "format": "u16", "readable": True},
        "C": {"offset": 2, "format": "u16", "readable": True},
        # eligible but non-contiguous
        "D": {"offset": 10, "format": "u16", "readable": True},
    }
    dev = _make_device_for_test(register_map)

    ranges = dev._build_bulk_ranges(max_regs_per_req=3)
    # Expect:
    # - A,B,C merged into one range (0..3)
    # - D alone into another range (10..11)
    assert len(ranges) == 2

    r0 = ranges[0]
    assert isinstance(r0, BulkRange)
    assert r0.start == 0
    assert r0.count == 3
    assert [name for name, _ in r0.items] == ["A", "B", "C"]

    r1 = ranges[1]
    assert r1.start == 10
    assert r1.count == 1
    assert [name for name, _ in r1.items] == ["D"]


def test_build_bulk_ranges_split_by_register_type():
    register_map = {
        "A": {"offset": 0, "format": "u16", "readable": True, "register_type": "holding"},
        "B": {"offset": 1, "format": "u16", "readable": True, "register_type": "holding"},
        "X": {"offset": 0, "format": "u16", "readable": True, "register_type": "input"},
        "Y": {"offset": 1, "format": "u16", "readable": True, "register_type": "input"},
    }
    dev = _make_device_for_test(register_map)

    ranges = dev._build_bulk_ranges(max_regs_per_req=120)
    # Expect 2 ranges, each grouped by register_type and contiguous offsets
    assert len(ranges) == 2
    assert {r.register_type for r in ranges} == {"holding", "input"}

    holding = next(r for r in ranges if r.register_type == "holding")
    assert holding.start == 0 and holding.count == 2
    assert [n for n, _ in holding.items] == ["A", "B"]

    input_r = next(r for r in ranges if r.register_type == "input")
    assert input_r.start == 0 and input_r.count == 2
    assert [n for n, _ in input_r.items] == ["X", "Y"]


async def test_read_all_bulk_success_maps_values_and_applies_post_process():
    register_map = {
        # Bulk eligible holding pins
        "A": {"offset": 0, "format": "u16", "readable": True},
        # with scale + precision
        "B": {"offset": 1, "format": "u16", "readable": True, "scale": 0.1, "precision": 1},
        # fallback pin (coil not bulk eligible)
        "C_COIL": {"offset": 5, "readable": True, "register_type": "coil"},
    }
    dev = _make_device_for_test(register_map)

    # Patch bus and per-pin bus cache:
    # Bulk range should be (start=0,count=2) -> regs [100, 1234]
    dev.bus = FakeBus(connected=True, regs_by_range={(0, 2): [100, 1234]})
    dev._bus_cache = {"holding": dev.bus}

    # Patch read_value for coil fallback
    async def _fake_read_value(name: str):
        if name == "C_COIL":
            return 1
        return DEFAULT_MISSING_VALUE

    dev.read_value = _fake_read_value  # type: ignore[method-assign]

    values = await dev.read_all()

    assert values["A"] == 100
    # B: 1234 * scale(0.1) = 123.4 rounded to 1 decimal
    assert values["B"] == 123.4
    # coil fallback
    assert values["C_COIL"] == 1


async def test_read_all_bulk_range_failure_sets_range_pins_missing_and_fallback_still_runs():
    register_map = {
        # Bulk eligible pins (same range)
        "A": {"offset": 0, "format": "u16", "readable": True},
        "B": {"offset": 1, "format": "u16", "readable": True},
        # Fallback pin (discrete_input not bulk eligible)
        "DI": {"offset": 7, "readable": True, "register_type": "discrete_input"},
    }
    dev = _make_device_for_test(register_map)

    # Bulk read fails for (0,2)
    dev.bus = FakeBus(connected=True, regs_by_range={}, raise_on={(0, 2)})
    dev._bus_cache = {"holding": dev.bus}

    async def _fake_read_value(name: str):
        if name == "DI":
            return 0
        return DEFAULT_MISSING_VALUE

    dev.read_value = _fake_read_value  # type: ignore[method-assign]

    values = await dev.read_all()

    assert values["A"] == DEFAULT_MISSING_VALUE
    assert values["B"] == DEFAULT_MISSING_VALUE
    # fallback still runs
    assert values["DI"] == 0


async def test_read_all_when_bus_offline_returns_default_offline_snapshot():
    register_map = {
        "A": {"offset": 0, "format": "u16", "readable": True},
        "B": {"offset": 1, "format": "u16", "readable": True},
        "X": {"offset": 5, "readable": False},  # unreadable should NOT appear
    }
    dev = _make_device_for_test(register_map)

    dev.bus = FakeBus(connected=False)
    dev._bus_cache = {"holding": dev.bus}

    values = await dev.read_all()

    assert values == {"A": DEFAULT_MISSING_VALUE, "B": DEFAULT_MISSING_VALUE}


async def test_read_all_computed_fields_applied():
    register_map = {
        "A": {"offset": 0, "format": "u16", "readable": True},
        "B": {"offset": 1, "format": "u16", "readable": True},
    }
    dev = _make_device_for_test(register_map)

    dev.bus = FakeBus(connected=True, regs_by_range={(0, 2): [10, 20]})
    dev._bus_cache = {"holding": dev.bus}

    values = await dev.read_all()

    assert values["A"] == 10
    assert values["B"] == 20
    assert values["A_plus_B"] == 30
