from unittest.mock import AsyncMock, Mock

import pytest

from core.executor.control_executor import ControlExecutor
from core.schema.control_condition_schema import ControlActionSchema, ControlActionType


@pytest.fixture
def mock_device_manager():
    """Create a mock device manager for testing"""
    return Mock()


@pytest.fixture
def mock_device():
    """Create a mock VFD device with common configuration"""
    device = Mock()
    device.model = "TECO_VFD"
    device.register_map = {
        "RW_HZ": {"writable": True},
        "RW_DO": {"writable": True},
        "RW_RESET": {"writable": True},
        "RO_STATUS": {"writable": False},  # Read-only register for testing
    }
    device.read_value = AsyncMock()
    device.write_value = AsyncMock()
    device.write_on_off = AsyncMock()
    device.supports_on_off = Mock(return_value=True)
    return device


@pytest.fixture
def mock_do_device():
    """Create a mock DO module device with common configuration"""
    device = Mock()
    device.model = "DO_MODULE"
    device.register_map = {
        "DO_01": {"writable": True},
        "DO_02": {"writable": True},
        "DO_03": {"writable": True},
        "DO_04": {"writable": True},
        "RW_DO": {"writable": True},  # Default target
    }
    device.read_value = AsyncMock()
    device.write_value = AsyncMock()
    return device


@pytest.fixture
def control_executor(mock_device_manager):
    """Create ControlExecutor instance with mocked dependencies"""
    return ControlExecutor(mock_device_manager)


@pytest.fixture
def mock_control_evaluator():
    """Create a mock ControlEvaluator for testing"""
    evaluator = Mock()
    evaluator.control_config = Mock()
    evaluator.evaluate = AsyncMock(return_value=[])
    return evaluator


# Common action fixtures
@pytest.fixture
def turn_on_action():
    """Create a TURN_ON action for testing"""
    return ControlActionSchema(model="TECO_VFD", slave_id="2", type=ControlActionType.TURN_ON)


@pytest.fixture
def turn_off_action():
    """Create a TURN_OFF action for testing"""
    return ControlActionSchema(model="TECO_VFD", slave_id="2", type=ControlActionType.TURN_OFF)


@pytest.fixture
def set_frequency_action():
    """Create a SET_FREQUENCY action for testing"""
    return ControlActionSchema(
        model="TECO_VFD", slave_id="2", type=ControlActionType.SET_FREQUENCY, target="RW_HZ", value=50.0
    )


@pytest.fixture
def adjust_frequency_action():
    """Create an ADJUST_FREQUENCY action for testing"""
    return ControlActionSchema(
        model="TECO_VFD", slave_id="2", type=ControlActionType.ADJUST_FREQUENCY, target="RW_HZ", value=2.5
    )


@pytest.fixture
def write_do_action():
    """Create a WRITE_DO action for testing"""
    return ControlActionSchema(
        model="DO_MODULE", slave_id="3", type=ControlActionType.WRITE_DO, target="DO_01", value=1  # Digital output pin
    )


@pytest.fixture
def reset_action():
    """Create a RESET action for testing"""
    return ControlActionSchema(model="TECO_VFD", slave_id="2", type=ControlActionType.RESET, target="RW_RESET", value=1)
