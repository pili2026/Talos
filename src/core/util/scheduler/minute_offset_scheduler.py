import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from core.evaluator.time_evalutor import TimeControlEvaluator
from core.util.time_util import TIMEZONE_INFO

logger = logging.getLogger(__name__)


@dataclass
class ScheduleRule:
    name: str
    callback: Callable[[datetime], Awaitable]
    trigger_minutes: list[int] | None = field(default=None)
    time: str | None = field(default=None)
    intervals: list[tuple[str, str]] | None = field(default=None)
    weekdays: list[int] | None = field(default=None)
    device_id: str | None = field(default=None)


class MinuteOffsetScheduler:
    def __init__(
        self, rules: list[ScheduleRule], evaluator: TimeControlEvaluator, timezone: ZoneInfo = TIMEZONE_INFO
    ) -> None:
        self._rules = rules
        self._evaluator = evaluator
        self._timezone = timezone
        self._last_fired: dict[str, int] = {}

    async def run(self) -> None:
        while True:
            datetime_now: datetime = datetime.now(self._timezone)
            minutes_since_midnight: int = datetime_now.hour * 60 + datetime_now.minute

            for rule in self._rules:
                await self._process_rule(rule, datetime_now, minutes_since_midnight)

            seconds_until_next_minute: int = 60 - datetime_now.second
            await asyncio.sleep(seconds_until_next_minute)

    async def _process_rule(self, rule: ScheduleRule, now: datetime, current_minute: int) -> None:
        # 1. Deduplication: skip if already fired this minute
        if self._last_fired.get(rule.name) == current_minute:
            return

        # 2. Trigger timing check
        if not self._is_trigger_time(rule, now):
            return

        # 3. Weekday check
        if rule.weekdays is not None and now.isoweekday() not in rule.weekdays:
            return

        # 4. Interval check
        if rule.intervals is not None and not self._in_any_interval(rule.intervals, now):
            return

        # 5. Evaluator check
        if rule.device_id is not None:
            if not self._evaluator.allow(rule.device_id, now):
                return

        # All checks passed — fire the callback
        self._last_fired[rule.name] = current_minute
        try:
            await rule.callback(now)
        except Exception:
            logger.error(f"[MinuteOffsetScheduler] Rule '{rule.name}' callback raised an exception", exc_info=True)

    @staticmethod
    def _is_trigger_time(rule: ScheduleRule, now: datetime) -> bool:
        if rule.trigger_minutes is not None:
            return now.minute in rule.trigger_minutes

        if rule.time is not None:
            hour_str, minute_str = rule.time.split(":")
            return now.hour == int(hour_str) and now.minute == int(minute_str)

        return False

    @staticmethod
    def _in_any_interval(intervals: list[tuple[str, str]], now: datetime) -> bool:
        current_minutes_since_midnight: int = now.hour * 60 + now.minute

        for start_str, end_str in intervals:
            start_hour, start_minute = map(int, start_str.split(":"))
            end_hour, end_minute = map(int, end_str.split(":"))
            interval_start_minutes = start_hour * 60 + start_minute
            interval_end_minutes = end_hour * 60 + end_minute

            if interval_start_minutes <= interval_end_minutes:
                if interval_start_minutes <= current_minutes_since_midnight <= interval_end_minutes:
                    return True
            else:
                # Overnight interval e.g. 22:00–06:00
                if (
                    current_minutes_since_midnight >= interval_start_minutes
                    or current_minutes_since_midnight <= interval_end_minutes
                ):
                    return True

        return False
