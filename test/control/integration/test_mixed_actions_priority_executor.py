"""
Executor Integration Tests — Priority Protection & Parallel Targets
- Verifies that for same device+target, higher-priority action wins
- Verifies that different targets execute side-by-side
"""

from unittest.mock import AsyncMock, Mock

import pytest

from core.executor.control_executor import ControlExecutor
from core.model.enum.condition_enum import ControlActionType
from core.schema.control_condition_schema import ControlActionSchema


@pytest.fixture
def mock_device():
    mock_device = Mock()
    mock_device.model = "TECO_VFD"
    mock_device.slave_id = "2"
    mock_device.register_map = {
        "RW_HZ": {"writable": True, "address": 8193},
        "RW_ON_OFF": {"writable": True, "address": 8192},
        "RW_DO": {"writable": True, "address": 8200},
    }
    mock_device.read_value = AsyncMock(return_value=50.0)
    mock_device.write_value = AsyncMock()
    mock_device.write_on_off = AsyncMock()
    mock_device.supports_on_off = Mock(return_value=True)
    return mock_device


@pytest.fixture
def mock_device_manager(mock_device):
    mgr = Mock()
    mgr.get_device_by_model_and_slave_id = Mock(return_value=mock_device)
    return mgr


@pytest.fixture
def executor(mock_device_manager) -> ControlExecutor:
    return ControlExecutor(mock_device_manager)


@pytest.mark.asyncio
async def test_when_two_actions_target_same_then_higher_priority_value_wins(executor: ControlExecutor):
    """Same device+target (RW_HZ): only one write — use higher priority's value."""
    # Mock
    mock_priority_high = Mock(spec=ControlActionSchema)
    mock_priority_high.model, mock_priority_high.slave_id = "TECO_VFD", "2"
    mock_priority_high.type = ControlActionType.SET_FREQUENCY
    mock_priority_high.target = "RW_HZ"
    mock_priority_high.value = 48.0
    mock_priority_high.priority = 10
    mock_priority_high.reason = "[p10]"

    mock_priority_low = Mock(spec=ControlActionSchema)
    mock_priority_low.model, mock_priority_low.slave_id = "TECO_VFD", "2"
    mock_priority_low.type = ControlActionType.SET_FREQUENCY
    mock_priority_low.target = "RW_HZ"
    mock_priority_low.value = 52.0
    mock_priority_low.priority = 20
    mock_priority_low.reason = "[p20]"

    # Act
    await executor.execute([mock_priority_high, mock_priority_low])
    device = executor.device_manager.get_device_by_model_and_slave_id("TECO_VFD", "2")

    # Assert
    device.write_value.assert_called_once_with("RW_HZ", 48.0)


@pytest.mark.asyncio
async def test_when_targets_differ_then_both_actions_are_written(executor: ControlExecutor):
    """Different targets (RW_HZ vs RW_DO): both writes occur."""
    # Mock
    mock_action_freq = Mock(spec=ControlActionSchema)
    mock_action_freq.model, mock_action_freq.slave_id = "TECO_VFD", "2"
    mock_action_freq.type = ControlActionType.SET_FREQUENCY
    mock_action_freq.target = "RW_HZ"
    mock_action_freq.value = 46.0
    mock_action_freq.priority = 10
    mock_action_freq.reason = "[freq]"

    mock_action_do = Mock(spec=ControlActionSchema)
    mock_action_do.model, mock_action_do.slave_id = "TECO_VFD", "2"
    mock_action_do.type = ControlActionType.WRITE_DO
    mock_action_do.target = "RW_DO"
    mock_action_do.value = 1
    mock_action_do.priority = 20
    mock_action_do.reason = "[do]"

    # Act
    await executor.execute([mock_action_freq, mock_action_do])
    device = executor.device_manager.get_device_by_model_and_slave_id("TECO_VFD", "2")
    device.write_value.assert_any_call("RW_HZ", 46.0)
    device.write_value.assert_any_call("RW_DO", 1)

    # Assert
    assert device.write_value.call_count == 2


@pytest.mark.asyncio
async def test_when_turn_on_with_explicit_target_then_calls_write_on_off_once(executor: ControlExecutor):
    """TURN_ON with explicit RW_ON_OFF target should call write_on_off(1)."""
    # Mock
    mock_action = Mock(spec=ControlActionSchema)
    mock_action.model, mock_action.slave_id = "TECO_VFD", "2"
    mock_action.type = ControlActionType.TURN_ON
    mock_action.target = "RW_ON_OFF"
    mock_action.value = 1
    mock_action.priority = 10
    mock_action.reason = "[turn_on]"

    # Act
    await executor.execute([mock_action])
    device = executor.device_manager.get_device_by_model_and_slave_id("TECO_VFD", "2")

    # Assert
    device.write_on_off.assert_called_once_with(1)
