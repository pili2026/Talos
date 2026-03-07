from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.evaluator.time_evalutor import TimeControlEvaluator
from core.util.scheduler.minute_offset_scheduler import MinuteOffsetScheduler, ScheduleRule
from core.util.time_util import TIMEZONE_INFO

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dt(hour: int, minute: int, iso_weekday: int, second: int = 0) -> datetime:
    """Build a tz-aware datetime; 2025-09-15 is Monday (weekday=1)."""
    base = datetime(2025, 9, 15, hour, minute, second, tzinfo=TIMEZONE_INFO)
    delta_days = iso_weekday - 1
    return base.replace(day=base.day + delta_days)


def _make_evaluator(allow_result: bool = True) -> TimeControlEvaluator:
    evaluator = MagicMock(spec=TimeControlEvaluator)
    evaluator.allow.return_value = allow_result
    return evaluator


def _make_scheduler(rules: list[ScheduleRule], allow_result: bool = True) -> MinuteOffsetScheduler:
    evaluator = _make_evaluator(allow_result)
    return MinuteOffsetScheduler(rules=rules, evaluator=evaluator, timezone=TIMEZONE_INFO)


# ---------------------------------------------------------------------------
# trigger_minutes mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_minutes_fires_on_matching_minute():
    callback = AsyncMock()
    rule = ScheduleRule(name="r1", callback=callback, trigger_minutes=[7, 37])
    scheduler = _make_scheduler([rule])

    now = _make_dt(10, 7, 1)
    await scheduler._process_rule(rule, now, now.hour * 60 + now.minute)

    callback.assert_awaited_once_with(now)


@pytest.mark.asyncio
async def test_trigger_minutes_does_not_fire_on_wrong_minute():
    callback = AsyncMock()
    rule = ScheduleRule(name="r1", callback=callback, trigger_minutes=[7, 37])
    scheduler = _make_scheduler([rule])

    now = _make_dt(10, 8, 1)
    await scheduler._process_rule(rule, now, now.hour * 60 + now.minute)

    callback.assert_not_awaited()


# ---------------------------------------------------------------------------
# time mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_time_mode_fires_at_exact_time():
    callback = AsyncMock()
    rule = ScheduleRule(name="r2", callback=callback, time="02:00")
    scheduler = _make_scheduler([rule])

    now = _make_dt(2, 0, 1)
    await scheduler._process_rule(rule, now, now.hour * 60 + now.minute)

    callback.assert_awaited_once_with(now)


@pytest.mark.asyncio
async def test_time_mode_does_not_fire_at_wrong_time():
    callback = AsyncMock()
    rule = ScheduleRule(name="r2", callback=callback, time="02:00")
    scheduler = _make_scheduler([rule])

    now = _make_dt(2, 1, 1)
    await scheduler._process_rule(rule, now, now.hour * 60 + now.minute)

    callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_time_mode_does_not_repeat_in_same_minute():
    callback = AsyncMock()
    rule = ScheduleRule(name="r2", callback=callback, time="02:00")
    scheduler = _make_scheduler([rule])

    now = _make_dt(2, 0, 1)
    minutes_since_midnight = now.hour * 60 + now.minute

    await scheduler._process_rule(rule, now, minutes_since_midnight)
    await scheduler._process_rule(rule, now, minutes_since_midnight)

    callback.assert_awaited_once()


# ---------------------------------------------------------------------------
# intervals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intervals_fires_when_inside_range():
    callback = AsyncMock()
    rule = ScheduleRule(name="r3", callback=callback, trigger_minutes=[0], intervals=[("08:00", "22:00")])
    scheduler = _make_scheduler([rule])

    now = _make_dt(10, 0, 1)
    await scheduler._process_rule(rule, now, now.hour * 60 + now.minute)

    callback.assert_awaited_once_with(now)


@pytest.mark.asyncio
async def test_intervals_does_not_fire_when_outside_range():
    callback = AsyncMock()
    rule = ScheduleRule(name="r3", callback=callback, trigger_minutes=[0], intervals=[("08:00", "22:00")])
    scheduler = _make_scheduler([rule])

    now = _make_dt(6, 0, 1)
    await scheduler._process_rule(rule, now, now.hour * 60 + now.minute)

    callback.assert_not_awaited()


# ---------------------------------------------------------------------------
# weekdays
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weekdays_fires_on_matching_day():
    callback = AsyncMock()
    rule = ScheduleRule(name="r4", callback=callback, trigger_minutes=[0], weekdays=[1, 2, 3, 4, 5])
    scheduler = _make_scheduler([rule])

    now = _make_dt(10, 0, 1)  # Monday
    await scheduler._process_rule(rule, now, now.hour * 60 + now.minute)

    callback.assert_awaited_once_with(now)


@pytest.mark.asyncio
async def test_weekdays_does_not_fire_on_non_matching_day():
    callback = AsyncMock()
    rule = ScheduleRule(name="r4", callback=callback, trigger_minutes=[0], weekdays=[1, 2, 3, 4, 5])
    scheduler = _make_scheduler([rule])

    now = _make_dt(10, 0, 7)  # Sunday
    await scheduler._process_rule(rule, now, now.hour * 60 + now.minute)

    callback.assert_not_awaited()


# ---------------------------------------------------------------------------
# evaluator.allow()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_allow_false_skips_callback():
    callback = AsyncMock()
    rule = ScheduleRule(name="r5", callback=callback, trigger_minutes=[0], device_id="pump")
    scheduler = _make_scheduler([rule], allow_result=False)

    now = _make_dt(10, 0, 1)
    await scheduler._process_rule(rule, now, now.hour * 60 + now.minute)

    callback.assert_not_awaited()
    scheduler._evaluator.allow.assert_called_once_with("pump", now)


@pytest.mark.asyncio
async def test_allow_true_fires_callback():
    callback = AsyncMock()
    rule = ScheduleRule(name="r5", callback=callback, trigger_minutes=[0], device_id="pump")
    scheduler = _make_scheduler([rule], allow_result=True)

    now = _make_dt(10, 0, 1)
    await scheduler._process_rule(rule, now, now.hour * 60 + now.minute)

    callback.assert_awaited_once_with(now)


# ---------------------------------------------------------------------------
# device_id not set → default allow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_device_id_fires_without_calling_allow():
    callback = AsyncMock()
    rule = ScheduleRule(name="r6", callback=callback, trigger_minutes=[0])
    evaluator = _make_evaluator(allow_result=False)  # would block if called
    scheduler = MinuteOffsetScheduler(rules=[rule], evaluator=evaluator, timezone=TIMEZONE_INFO)

    now = _make_dt(10, 0, 1)
    await scheduler._process_rule(rule, now, now.hour * 60 + now.minute)

    callback.assert_awaited_once_with(now)
    evaluator.allow.assert_not_called()


# ---------------------------------------------------------------------------
# Exception handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_callback_exception_does_not_stop_other_rules():
    failing_callback = AsyncMock(side_effect=RuntimeError("boom"))
    ok_callback = AsyncMock()

    rule_fail = ScheduleRule(name="fail", callback=failing_callback, trigger_minutes=[0])
    rule_ok = ScheduleRule(name="ok", callback=ok_callback, trigger_minutes=[0])

    evaluator = _make_evaluator()
    scheduler = MinuteOffsetScheduler(rules=[rule_fail, rule_ok], evaluator=evaluator, timezone=TIMEZONE_INFO)

    now = _make_dt(10, 0, 1)
    minutes_since_midnight = now.hour * 60 + now.minute

    await scheduler._process_rule(rule_fail, now, minutes_since_midnight)
    await scheduler._process_rule(rule_ok, now, minutes_since_midnight)

    failing_callback.assert_awaited_once()
    ok_callback.assert_awaited_once_with(now)


# ---------------------------------------------------------------------------
# Deduplication: same rule same minute
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_rule_same_minute_does_not_fire_twice():
    callback = AsyncMock()
    rule = ScheduleRule(name="dedup", callback=callback, trigger_minutes=[5])
    scheduler = _make_scheduler([rule])

    now = _make_dt(10, 5, 1)
    minutes_since_midnight = now.hour * 60 + now.minute

    await scheduler._process_rule(rule, now, minutes_since_midnight)
    await scheduler._process_rule(rule, now, minutes_since_midnight)

    callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_same_rule_different_minute_fires_again():
    callback = AsyncMock()
    rule = ScheduleRule(name="dedup2", callback=callback, trigger_minutes=[5, 6])
    scheduler = _make_scheduler([rule])

    now1 = _make_dt(10, 5, 1)
    now2 = _make_dt(10, 6, 1)

    await scheduler._process_rule(rule, now1, now1.hour * 60 + now1.minute)
    await scheduler._process_rule(rule, now2, now2.hour * 60 + now2.minute)

    assert callback.await_count == 2
