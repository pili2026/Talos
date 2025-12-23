import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from core.schema.control_condition_schema import ControlActionType
from core.schema.time_control_schema import DeviceSchedule, TimeControlConfig
from core.util.time_util import TIMEZONE_INFO

logger = logging.getLogger("TimeControlEvaluator")


class TimeControlEvaluator:
    """
    Use Pydantic schema (TimeControlConfig) as the single source of truth
    to determine whether a device is within allowed hours, and return
    TURN_ON / TURN_OFF actions when the state changes.

    Behavior:
      - allow(device_id): only checks "is it currently allowed?"
      - evaluate_action(device_id): on the first call returns the current state's
        action; afterward only returns an action when the state changes
    """

    def __init__(self, config: TimeControlConfig):
        self._config: TimeControlConfig = config
        self._default_tz: ZoneInfo = ZoneInfo(config.timezone) if config.timezone else TIMEZONE_INFO
        self._last_allowed_by_device: dict[str, bool] = {}

    # ---------- Public API ----------

    def allow(self, device_id: str, now: datetime | None = None) -> bool:
        """Return whether the current time (with timezone) is within allowed intervals."""
        schedule, tz = self._resolve_schedule_and_tz(device_id)
        if schedule is None:
            logger.debug(f"[TimeControlEvaluator] No config for {device_id}, no working time limit.")
            return True

        local_now = (now or datetime.now(self._default_tz)).astimezone(tz)
        if schedule.weekdays and local_now.isoweekday() not in schedule.weekdays:
            self._debug(device_id, local_now, schedule, allowed=False)
            return False

        now_t = local_now.time()
        allowed = any(self._in_interval(now_t, itv.start, itv.end) for itv in schedule.intervals)
        self._debug(device_id, local_now, schedule, allowed=allowed)
        return allowed

    def evaluate_action(self, device_id: str, now: datetime | None = None) -> ControlActionType | None:
        """
        - First call: return the action corresponding to the current state (TURN_ON or TURN_OFF)
        - Subsequent calls: only return an action when the state changes (allowed ↔ not allowed),
          otherwise return None
        """
        allowed_now = self.allow(device_id, now)
        last_allowed = self._last_allowed_by_device.get(device_id)

        if last_allowed is None:
            self._last_allowed_by_device[device_id] = allowed_now
            return ControlActionType.TURN_ON if allowed_now else ControlActionType.TURN_OFF

        action: ControlActionType | None = None
        if allowed_now and not last_allowed:
            action = ControlActionType.TURN_ON
        elif not allowed_now and last_allowed:
            action = ControlActionType.TURN_OFF

        self._last_allowed_by_device[device_id] = allowed_now
        return action

    # ---------- Private helpers ----------

    def _resolve_schedule_and_tz(self, device_id: str) -> tuple[DeviceSchedule | None, ZoneInfo]:
        """Return (DeviceSchedule, timezone); if not found, return (None, default_tz)."""
        work_hours: dict[str, DeviceSchedule] = self._config.work_hours
        schedule: DeviceSchedule | None = work_hours.get(device_id) or work_hours.get("default")
        if schedule is None:
            return None, self._default_tz

        tz = ZoneInfo(schedule.timezone) if schedule.timezone else self._default_tz
        return schedule, tz

    @staticmethod
    def _in_interval(current: time, start_t: time, end_t: time) -> bool:
        """Check if current is within [start_t, end_t] (inclusive); supports overnight (start > end)."""
        if start_t <= end_t:
            return start_t <= current <= end_t
        # Overnight interval: e.g. 22:00–06:00
        return current >= start_t or current <= end_t

    @staticmethod
    def _fmt_intervals(schedule: DeviceSchedule) -> str:
        return str([(i.start.isoformat(), i.end.isoformat()) for i in schedule.intervals])

    def _debug(self, device_id: str, local_now: datetime, schedule: DeviceSchedule, allowed: bool) -> None:
        try:
            tz_key = local_now.tzinfo.key  # type: ignore[attr-defined]
        except Exception:
            tz_key = str(local_now.tzinfo)
        logger.debug(
            f"[TimeControl] {device_id} now={local_now.strftime('%Y-%m-%d %H:%M:%S')} "
            f"tz={tz_key} wd={local_now.isoweekday()} "
            f"intervals={self._fmt_intervals(schedule)} → allowed={allowed}"
        )
