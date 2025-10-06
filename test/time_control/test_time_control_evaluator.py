import pytest
from time_control.conftest import _build_datetime

from schema.control_condition_schema import ControlActionType


@pytest.mark.parametrize(
    "target_id, hour, minute, weekday, expected",
    [
        ("DEVICE_1", 8, 0, 1, True),  # Monday at 08:00
        ("DEVICE_1", 18, 0, 1, True),  # Monday at 18:00
        ("DEVICE_1", 7, 59, 1, False),  # Monday before start
        ("DEVICE_1", 18, 1, 1, False),  # Monday after end
        ("DEVICE_1", 12, 0, 7, False),  # Sunday not in workdays
        ("UNKNOWN_DEVICE", 10, 0, 2, True),  # fallback to default
        ("UNKNOWN_DEVICE", 8, 0, 2, False),  # before default start
    ],
)
def test_when_checking_allow_then_result_should_match_expected(evaluator, target_id, hour, minute, weekday, expected):
    # Arrange
    stub_datetime = _build_datetime(hour, minute, weekday)

    # Act
    result = evaluator.allow(target_id, stub_datetime)

    # Assert
    assert result is expected


def test_when_first_time_and_allowed_then_return_turn_on(evaluator):
    # Arrange
    stub_datetime = _build_datetime(9, 0, 1)

    # Act
    action = evaluator.evaluate_action("DEVICE_1", stub_datetime)

    # Assert
    assert action == ControlActionType.TURN_ON


def test_when_first_time_and_disallowed_then_return_turn_off(evaluator):
    # Arrange
    stub_datetime = _build_datetime(7, 0, 1)

    # Act
    action = evaluator.evaluate_action("DEVICE_1", stub_datetime)

    # Assert
    assert action == ControlActionType.TURN_OFF


def test_when_device_status_unchanged_then_do_nothing(evaluator):
    # Arrange
    initial_time = _build_datetime(10, 0, 1)
    next_time = _build_datetime(11, 0, 1)

    # Act
    evaluator.evaluate_action("DEVICE_1", initial_time)
    result = evaluator.evaluate_action("DEVICE_1", next_time)

    # Assert
    assert result is None


def test_when_status_changes_from_allowed_to_disallowed_then_return_turn_off(evaluator):
    # Arrange
    initial_time = _build_datetime(10, 0, 1)  # Allowed
    next_time = _build_datetime(19, 0, 1)  # After work

    # Act
    evaluator.evaluate_action("DEVICE_1", initial_time)
    result = evaluator.evaluate_action("DEVICE_1", next_time)

    # Assert
    assert result == ControlActionType.TURN_OFF


def test_when_status_changes_from_disallowed_to_allowed_then_return_turn_on(evaluator):
    # Arrange
    initial_time = _build_datetime(7, 0, 1)  # Disallowed
    next_time = _build_datetime(9, 0, 1)  # Allowed

    # Act
    evaluator.evaluate_action("DEVICE_1", initial_time)
    result = evaluator.evaluate_action("DEVICE_1", next_time)

    # Assert
    assert result == ControlActionType.TURN_ON
