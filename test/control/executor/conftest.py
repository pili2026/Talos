# test/conftest.py
import logging

import pytest

from executor.control_executor import ControlExecutor
from model.control_model import ControlActionModel

# ----------------------
# Auto fixtures
# ----------------------


@pytest.fixture(autouse=True)
def _capture_control_executor_info_logs(caplog):
    """
    Auto-use fixture to capture INFO-level logs from ControlExecutor
    so tests can assert on [SKIP]/[WRITE] messages.
    """
    caplog.set_level(logging.INFO, logger="ControlExecutor")


# ----------------------
# Fake classes for Executor testing
# ----------------------


class FakeDevice:
    def __init__(self, model="SD400", registers=None, initial_values=None, support_onoff=True):
        self.model = model
        self.register_map = registers or {}
        self._values = dict(initial_values or {})
        self._writes = []  # log of (name, value) writes
        self._support_onoff = support_onoff
        self.fail_reads = set()
        self.fail_writes = set()

    def supports_on_off(self) -> bool:
        return self._support_onoff

    async def read_value(self, name: str):
        if name in self.fail_reads:
            raise RuntimeError("Injected read failure")
        return self._values.get(name, 0 if name == "RW_ON_OFF" else None)

    async def write_on_off(self, value: int):
        self._writes.append(("RW_ON_OFF", value))
        self._values["RW_ON_OFF"] = value

    async def write_value(self, name: str, value):
        if name in self.fail_writes:
            raise RuntimeError("Injected write failure")
        self._writes.append((name, value))
        self._values[name] = value


class FakeDeviceManager:
    def __init__(self):
        self._devices = {}

    def add(self, model: str, slave_id: str, device: FakeDevice):
        self._devices[f"{model}_{slave_id}"] = device

    def get_device_by_model_and_slave_id(self, model: str, slave_id: str):
        return self._devices.get(f"{model}_{slave_id}")


# ----------------------
# Common fixtures
# ----------------------


@pytest.fixture
def make_executor():
    def _make():
        fake_device_manager = FakeDeviceManager()
        executor = ControlExecutor(fake_device_manager)
        return executor, fake_device_manager

    return _make


@pytest.fixture
def make_action():
    def _make(**kwargs):
        return ControlActionModel(**kwargs)

    return _make


@pytest.fixture
def make_device():
    """
    Factory to create a FakeDevice for executor tests.
    Usage:
        dev = make_device(registers={"RW_HZ": {"writable": True}}, initial_values={"RW_HZ": 40.0})
    """

    def _make(*, model="SD400", registers=None, initial_values=None, support_onoff=True):
        return FakeDevice(model=model, registers=registers, initial_values=initial_values, support_onoff=support_onoff)

    return _make
