import pytest
from time_control.conftest import _build_datetime

from core.schema.control_condition_schema import ControlActionType


@pytest.mark.parametrize(
    "target_id, hour, minute, weekday, expected",
    [
        ("DEVICE_1", 8, 0, 1, True),  # Mon 08:00 → in
        ("DEVICE_1", 18, 0, 1, True),  # Mon 18:00 → endpoint inclusive
        ("DEVICE_1", 7, 59, 1, False),  # Mon before start
        ("DEVICE_1", 18, 1, 1, False),  # Mon after end
        ("DEVICE_1", 12, 0, 7, False),  # Sun not in weekdays
        ("UNKNOWN_DEVICE", 10, 0, 2, True),  # Tue 10:00 → use default(09:00–17:00)
        ("UNKNOWN_DEVICE", 8, 0, 2, False),  # Tue 08:00 → before default start
    ],
)
def test_allow_matches_expected(evaluator, target_id, hour, minute, weekday, expected):
    now = _build_datetime(hour, minute, weekday)
    assert evaluator.allow(target_id, now) is expected


def test_first_time_allowed_returns_turn_on(evaluator):
    now = _build_datetime(9, 0, 1)
    assert evaluator.evaluate_action("DEVICE_1", now) == ControlActionType.TURN_ON


def test_first_time_disallowed_returns_turn_off(evaluator):
    now = _build_datetime(7, 0, 1)
    assert evaluator.evaluate_action("DEVICE_1", now) == ControlActionType.TURN_OFF


def test_no_action_when_status_unchanged(evaluator):
    t1 = _build_datetime(10, 0, 1)
    t2 = _build_datetime(11, 0, 1)
    evaluator.evaluate_action("DEVICE_1", t1)
    assert evaluator.evaluate_action("DEVICE_1", t2) is None


def test_turn_off_when_allowed_to_disallowed(evaluator):
    t1 = _build_datetime(10, 0, 1)  # in
    t2 = _build_datetime(19, 0, 1)  # out
    evaluator.evaluate_action("DEVICE_1", t1)
    assert evaluator.evaluate_action("DEVICE_1", t2) == ControlActionType.TURN_OFF


def test_turn_on_when_disallowed_to_allowed(evaluator):
    t1 = _build_datetime(7, 0, 1)  # out
    t2 = _build_datetime(9, 0, 1)  # in
    evaluator.evaluate_action("DEVICE_1", t1)
    assert evaluator.evaluate_action("DEVICE_1", t2) == ControlActionType.TURN_ON
    assert evaluator.evaluate_action("DEVICE_1", t2) is None
