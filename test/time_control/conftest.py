from datetime import datetime, time

import pytest

from core.evaluator.time_evalutor import TimeControlEvaluator
from core.schema.time_control_schema import DeviceSchedule, TimeControlConfig, TimeInterval
from core.util.time_util import TIMEZONE_INFO


def _build_datetime(hour: int, minute: int, iso_weekday: int) -> datetime:
    """
    Build a timezone-aware test datetime (iso_weekday: 1=Mon...7=Sun).
    The actual calendar date doesn't matter much; changing weekday
    within the same base date is sufficient. If needed, adjust with a real calendar.
    """
    # 2025-09-15 is a Monday (1), so add (iso_weekday-1) days to shift weekday
    base = datetime(2025, 9, 15, hour, minute, 0, tzinfo=TIMEZONE_INFO)
    delta_days = iso_weekday - 1
    return base.replace(day=base.day + delta_days)


@pytest.fixture
def evaluator() -> TimeControlEvaluator:
    """
    Test configuration:
      DEVICE_1: Weekdays (1..5) 08:00-18:00
      default : Weekdays (1..5) 09:00-17:00
    """
    cfg = TimeControlConfig(
        timezone="Asia/Taipei",
        work_hours={
            "DEVICE_1": DeviceSchedule(
                weekdays={1, 2, 3, 4, 5},
                intervals=[TimeInterval(start=time.fromisoformat("08:00"), end=time.fromisoformat("18:00"))],
            ),
            "default": DeviceSchedule(
                weekdays={1, 2, 3, 4, 5},
                intervals=[TimeInterval(start=time.fromisoformat("09:00"), end=time.fromisoformat("17:00"))],
            ),
        },
    )
    return TimeControlEvaluator(cfg)
