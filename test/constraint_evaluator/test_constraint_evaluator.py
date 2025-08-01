from unittest.mock import AsyncMock, MagicMock

import pytest

from evaluator.constraint_evaluator import ConstraintEvaluate
from model.control_model import ControlActionModel, ControlActionType


@pytest.mark.asyncio
async def test_when_value_below_min_then_correct_and_publish_action():
    # Mock
    mock_pubsub = AsyncMock()
    executor = ConstraintEvaluate(pubsub=mock_pubsub)

    mock_device = MagicMock()
    mock_device.model = "SD400"
    mock_device.slave_id = 3
    mock_device.constraints = {"TEMP": {"min": 30, "max": 60}}

    # Arrange
    fake_snapshot = {"TEMP": 20}

    # Act
    await executor.evaluate(mock_device, fake_snapshot)

    # Assert
    mock_pubsub.publish.assert_called_once()
    action: ControlActionModel = mock_pubsub.publish.call_args.args[1]
    assert action.type == ControlActionType.SET_FREQUENCY
    assert action.target == "TEMP"
    assert action.value == 30
    assert action.source == "ConstraintEnforcer"
    assert "out of range" in action.reason


@pytest.mark.asyncio
async def test_when_value_above_max_then_correct_and_publish_action():
    # Mock
    mock_pubsub = AsyncMock()
    executor = ConstraintEvaluate(pubsub=mock_pubsub)

    mock_device = MagicMock()
    mock_device.model = "SD400"
    mock_device.slave_id = 3
    mock_device.constraints = {"PRESSURE": {"min": 10, "max": 40}}

    # Arrange
    fake_snapshot = {"PRESSURE": 55}

    # Act
    await executor.evaluate(mock_device, fake_snapshot)

    # Assert
    mock_pubsub.publish.assert_called_once()
    action: ControlActionModel = mock_pubsub.publish.call_args.args[1]
    assert action.value == 40
    assert action.target == "PRESSURE"


@pytest.mark.asyncio
async def test_when_value_within_range_then_do_nothing():
    # Mock
    mock_pubsub = AsyncMock()
    executor = ConstraintEvaluate(pubsub=mock_pubsub)

    mock_device = MagicMock()
    mock_device.model = "SD400"
    mock_device.slave_id = 3
    mock_device.constraints = {"TEMP": {"min": 30, "max": 60}}

    # Arrange
    fake_snapshot = {"TEMP": 45}

    # Act
    await executor.evaluate(mock_device, fake_snapshot)

    # Assert
    mock_pubsub.publish.assert_not_called()


@pytest.mark.asyncio
async def test_when_multiple_values_then_only_violations_trigger():
    # Mock
    mock_pubsub = AsyncMock()
    executor = ConstraintEvaluate(pubsub=mock_pubsub)

    mock_device = MagicMock()
    mock_device.model = "SD400"
    mock_device.slave_id = 3
    mock_device.constraints = {"TEMP": {"min": 30, "max": 60}, "FLOW": {"min": 10, "max": 20}}

    # Arrange
    fake_snapshot = {
        "TEMP": 20,  # below min → trigger
        "FLOW": 15,  # within range → no action
    }

    # Act
    await executor.evaluate(mock_device, fake_snapshot)

    # Assert
    mock_pubsub.publish.assert_called_once()
    action: ControlActionModel = mock_pubsub.publish.call_args.args[1]
    assert action.target == "TEMP"
    assert action.value == 30


@pytest.mark.asyncio
async def test_when_target_not_in_constraints_then_ignore():
    # Mock
    mock_pubsub = AsyncMock()
    executor = ConstraintEvaluate(pubsub=mock_pubsub)

    mock_device = MagicMock()
    mock_device.model = "SD400"
    mock_device.slave_id = 3
    mock_device.constraints = {}  # no constraints at all

    # Arrange
    fake_snapshot = {"VOLTAGE": 300}

    # Act
    await executor.evaluate(mock_device, fake_snapshot)

    # Assert
    mock_pubsub.publish.assert_not_called()
