import logging
from datetime import datetime, time

from model.control_model import ControlActionType

logger = logging.getLogger("TimeControlEvaluator")


class TimeControlEvaluator:
    def __init__(self, work_hours: dict[str, dict]):
        self.work_hours = work_hours
        self._last_status = {}  # device_id -> bool (True=allowed, False=forbidden)

    def allow(self, target_id: str, time_now: datetime | None = None) -> bool:
        """Check if the current time is within allowed work hours for the target."""
        time_now = time_now or datetime.now()
        time_config = self.work_hours.get(target_id) or self.work_hours.get("default")

        if not time_config:
            logger.warning(f"[TimeControl] No config for {target_id}, allow by default.")
            return True

        if time_now.isoweekday() not in time_config["weekdays"]:
            return False

        start_time = time.fromisoformat(time_config["start"])
        end_time = time.fromisoformat(time_config["end"])
        return start_time <= time_now.time() <= end_time

    def evaluate_action(self, target_id: str, time_now: datetime | None = None) -> ControlActionType | None:
        """
        Evaluate and return the required action for a device based on time rules:
        - TURN_OFF if previously allowed and now not allowed
        - TURN_ON if previously not allowed and now allowed
        - None if no change
        """
        allowed: bool = self.allow(target_id, time_now)
        last_allowed: bool = self._last_status.get(target_id, True)

        action = None
        if not allowed and last_allowed:
            action = ControlActionType.TURN_OFF
        elif allowed and not last_allowed:
            action = ControlActionType.TURN_ON

        self._last_status[target_id] = allowed
        return action
