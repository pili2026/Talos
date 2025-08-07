from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from evaluator.time_evalutor import TimeControlEvaluator
from time_control_handler import TimeControlHandler


@pytest.fixture
def mock_pubsub():
    return AsyncMock()


@pytest.fixture
def mock_executor():
    return AsyncMock()


@pytest.fixture
def mock_evaluator():
    evaluator = MagicMock()
    evaluator.evaluate_action.return_value = None
    evaluator.allow.return_value = True
    return evaluator


@pytest.fixture
def time_control_handler(mock_pubsub, mock_executor, mock_evaluator):
    return TimeControlHandler(
        pubsub=mock_pubsub,
        time_control_evaluator=mock_evaluator,
        executor=mock_executor,
        expected_devices={"DEVICE_1"},
    )


WORK_HOURS = {
    "DEVICE_1": {
        "weekdays": [1, 2, 3, 4, 5],  # Monday to Friday
        "start": "08:00",
        "end": "18:00",
    },
    "default": {
        "weekdays": [1, 2, 3, 4, 5],
        "start": "09:00",
        "end": "17:00",
    },
}


@pytest.fixture
def evaluator():
    return TimeControlEvaluator(WORK_HOURS)


def _build_datetime(hour: int, minute: int, weekday: int) -> datetime:
    base = datetime(2024, 8, 5)  # Monday
    delta = timedelta(days=weekday - base.isoweekday())
    return base.replace(hour=hour, minute=minute) + delta
