import pytest

from model.control_model import ControlActionType
from util.pubsub.pubsub_topic import PubSubTopic


@pytest.mark.asyncio
async def test_when_device_allowed_then_send_turn_on_and_publish_snapshot(
    time_control_handler, mock_evaluator, mock_executor, mock_pubsub
):
    # Arrange
    snapshot = {"device_id": "DEVICE_1", "slave_id": 1}

    # Mock
    mock_evaluator.evaluate_action.return_value = ControlActionType.TURN_ON
    mock_evaluator.allow.return_value = True

    # Act
    await time_control_handler.handle_snapshot(snapshot)

    # Assert
    mock_executor.send_control.assert_awaited_once_with(
        "DEVICE_1", "DEVICE", 1, ControlActionType.TURN_ON, "On timezone auto startup"
    )

    mock_pubsub.publish.assert_awaited_with(PubSubTopic.SNAPSHOT_ALLOWED, snapshot)


@pytest.mark.asyncio
async def test_when_device_disallowed_then_send_turn_off_and_skip_snapshot(
    time_control_handler, mock_evaluator, mock_executor, mock_pubsub
):
    # Arrange
    snapshot = {"device_id": "DEVICE_1", "slave_id": 1}

    # Mock
    mock_evaluator.evaluate_action.return_value = ControlActionType.TURN_OFF
    mock_evaluator.allow.return_value = False

    # Act
    await time_control_handler.handle_snapshot(snapshot)

    # Assert
    mock_executor.send_control.assert_awaited_once_with(
        "DEVICE_1", "DEVICE", 1, ControlActionType.TURN_OFF, "Off timezone auto shutdown"
    )
    mock_pubsub.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_when_device_status_unchanged_then_do_nothing_but_publish_snapshot(
    time_control_handler, mock_evaluator, mock_executor, mock_pubsub
):
    # Arrange
    snapshot = {"device_id": "DEVICE_1", "slave_id": 1}

    # Mock
    mock_evaluator.evaluate_action.return_value = None
    mock_evaluator.allow.return_value = True

    # Act
    await time_control_handler.handle_snapshot(snapshot)

    # Assert
    mock_executor.send_control.assert_not_awaited()
    mock_pubsub.publish.assert_awaited_with(PubSubTopic.SNAPSHOT_ALLOWED, snapshot)


@pytest.mark.asyncio
async def test_when_snapshot_missing_device_id_then_ignore_snapshot(time_control_handler, mock_executor, mock_pubsub):
    # Arrange
    snapshot = {"slave_id": 1}  # device_id is missing

    # Act
    await time_control_handler.handle_snapshot(snapshot)

    # Mock
    mock_executor.send_control.assert_not_called()
    mock_pubsub.publish.assert_not_called()
