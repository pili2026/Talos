import logging
from datetime import datetime

from core.model.enum.alert_state_enum import AlertState
from core.schema.alert_schema import AlertSeverity
from core.util.time_util import TIMEZONE_INFO


class AlertStateRecord:
    """Single alert state record"""

    def __init__(
        self,
        device_id: str,
        alert_code: str,
        state: AlertState,
        severity: AlertSeverity,
        triggered_at: datetime | None = None,
        resolved_at: datetime | None = None,
        last_value: float | None = None,
    ):
        self.device_id = device_id
        self.alert_code = alert_code
        self.state = state
        self.severity = severity
        self.triggered_at = triggered_at
        self.resolved_at = resolved_at
        self.last_value = last_value


class AlertStateManager:
    """
    Manages alert states to prevent duplicate notifications.

    State transitions:
    - NORMAL → TRIGGERED: First violation (notify)
    - TRIGGERED → ACTIVE: Continuous violation (no notify)
    - ACTIVE → RESOLVED: Recovered (notify)
    - RESOLVED → NORMAL: Cleanup (no notify)

    Current: Memory-based storage (dict)
    Future: SQLite persistence (see docs/alert_state_schema.sql)

    Migration path:
    1. Add SQLite backend option
    2. Load existing states on startup
    3. Persist state changes to DB
    4. Keep memory dict as cache
    """

    def __init__(self):
        # Key: (device_id, alert_code), Value: AlertStateRecord
        self.states: dict[tuple[str, str], AlertStateRecord] = {}
        self.logger = logging.getLogger(__class__.__name__)

    def get_state(self, device_id: str, alert_code: str) -> AlertState:
        """Get current state for an alert"""
        key = (device_id, alert_code)
        record = self.states.get(key)
        return record.state if record else AlertState.NORMAL

    def should_notify(
        self,
        device_id: str,
        alert_code: str,
        is_triggered: bool,
        severity: AlertSeverity,
        current_value: float,
    ) -> tuple[bool, str | None]:
        """
        Determine if notification should be sent based on state transition.

        Returns:
            (should_notify: bool, notification_type: Optional[str])
            notification_type can be "TRIGGERED" or "RESOLVED"
        """
        current_state: AlertState = self.get_state(device_id, alert_code)

        # Case 1: Alert triggered
        if is_triggered:
            if current_state == AlertState.NORMAL:
                # NORMAL → TRIGGERED: First violation, send notification
                self._update_state(
                    device_id=device_id,
                    alert_code=alert_code,
                    new_state=AlertState.TRIGGERED,
                    severity=severity,
                    current_value=current_value,
                )
                return (True, AlertState.TRIGGERED.name)

            if current_state == AlertState.TRIGGERED:
                # TRIGGERED → ACTIVE: Continuous violation, no notification
                self._update_state(
                    device_id=device_id,
                    alert_code=alert_code,
                    new_state=AlertState.ACTIVE,
                    severity=severity,
                    current_value=current_value,
                )
                return (False, None)

            if current_state == AlertState.ACTIVE:
                # ACTIVE → ACTIVE: Still violated, no notification
                self._update_value(device_id, alert_code, current_value)
                return (False, None)

            if current_state == AlertState.RESOLVED:
                # RESOLVED → TRIGGERED: Re-triggered after recovery
                self._update_state(
                    device_id=device_id,
                    alert_code=alert_code,
                    new_state=AlertState.TRIGGERED,
                    severity=severity,
                    current_value=current_value,
                )
                return (True, AlertState.TRIGGERED.name)

        # Case 2: Alert not triggered (condition normalized)
        else:
            if current_state in (AlertState.TRIGGERED, AlertState.ACTIVE):
                # TRIGGERED/ACTIVE → RESOLVED: Recovered, send notification
                self._update_state(
                    device_id=device_id,
                    alert_code=alert_code,
                    new_state=AlertState.RESOLVED,
                    severity=severity,
                    current_value=current_value,
                )
                return (True, AlertState.RESOLVED.name)

            if current_state == AlertState.RESOLVED:
                # RESOLVED → NORMAL: Cleanup
                self._remove_state(device_id, alert_code)
                return (False, None)

        # Default: no notification
        return (False, None)

    def get_all_active_alerts(self) -> list[AlertStateRecord]:
        """Get all alerts in TRIGGERED or ACTIVE state"""
        return [record for record in self.states.values() if record.state in (AlertState.TRIGGERED, AlertState.ACTIVE)]

    def clear_all(self):
        """Clear all states (for testing or reset)"""
        self.states.clear()
        self.logger.info("[STATE] All states cleared")

    def _update_state(
        self,
        device_id: str,
        alert_code: str,
        new_state: AlertState,
        severity: AlertSeverity,
        current_value: float,
    ):
        """Update alert state and log transition"""
        key = (device_id, alert_code)
        old_state = self.get_state(device_id, alert_code)

        now = datetime.now(TIMEZONE_INFO)

        if new_state == AlertState.TRIGGERED:
            triggered_at = now
            resolved_at = None
        elif new_state == AlertState.RESOLVED:
            triggered_at = self.states[key].triggered_at if key in self.states else now
            resolved_at = now
        else:
            triggered_at = self.states[key].triggered_at if key in self.states else None
            resolved_at = None

        self.states[key] = AlertStateRecord(
            device_id=device_id,
            alert_code=alert_code,
            state=new_state,
            severity=severity,
            triggered_at=triggered_at,
            resolved_at=resolved_at,
            last_value=current_value,
        )

        self.logger.info(
            f"[STATE] [{device_id}] {alert_code}: {old_state} → {new_state} " f"(value={current_value:.2f})"
        )

    def _update_value(self, device_id: str, alert_code: str, current_value: float):
        """Update last value without changing state"""
        key = (device_id, alert_code)
        if key in self.states:
            self.states[key].last_value = current_value

    def _remove_state(self, device_id: str, alert_code: str):
        """Remove state record (cleanup after RESOLVED → NORMAL)"""
        key = (device_id, alert_code)
        if key in self.states:
            self.logger.info(f"[STATE] [{device_id}] {alert_code}: Cleared")
            del self.states[key]
