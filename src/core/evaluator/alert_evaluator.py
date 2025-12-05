import logging
from collections import Counter

from core.evaluator.alert_state_manager import AlertStateManager
from core.evaluator.time_evalutor import TimeControlEvaluator
from core.model.enum.alert_enum import AlertSeverity
from core.model.enum.alert_state_enum import AlertState
from core.model.enum.condition_enum import ConditionOperator, ConditionType
from core.schema.alert_config_schema import AlertConfig
from core.schema.alert_schema import (
    AggregateAlertConfig,
    AlertConditionModel,
    ScheduleExpectedStateAlertConfig,
    ThresholdAlertConfig,
)

logger = logging.getLogger("AlertEvaluator")


class AlertEvaluator:
    def __init__(
        self,
        alert_config: AlertConfig,
        valid_device_ids: set[str],
        time_control_evaluator: TimeControlEvaluator | None = None,
    ):
        # Nest struct: { model: { slave_id: [AlertConditionModel] } }
        self.device_alert_dict: dict[str, dict[str, list[AlertConditionModel]]] = {}

        total_alerts = 0
        total_devices = 0
        skipped_devices = 0
        alert_type_counter = Counter()
        severity_counter = Counter()
        model_alert_counts = {}  # { model: { slave_id: count } }

        for model, model_config in alert_config.root.items():
            self.device_alert_dict[model] = {}
            model_alert_counts[model] = {}

            for slave_id in model_config.instances:
                device_id = f"{model}_{slave_id}"

                if device_id not in valid_device_ids:
                    logger.warning(f"[SKIP] Unknown device in config: {device_id}")
                    skipped_devices += 1
                    continue

                alerts = alert_config.get_instance_alerts(model, slave_id)
                if alerts:
                    self.device_alert_dict[model][slave_id] = alerts
                    total_devices += 1
                    total_alerts += len(alerts)
                    model_alert_counts[model][slave_id] = len(alerts)

                    for alert in alerts:
                        alert_type_counter[alert.type.value] += 1
                        severity_counter[alert.severity.value] += 1

                    logger.info(f"[{device_id}] Loaded {len(alerts)} alerts")
                else:
                    logger.debug(f"[{device_id}] No alert configured. Skipped.")

        self.state_manager = AlertStateManager()
        self.time_control_evaluator = time_control_evaluator

        logger.info("=" * 60)
        logger.info("AlertEvaluator Initialization Summary")
        logger.info("=" * 60)
        logger.info(f"Configuration Version: {alert_config.version}")
        logger.info(
            f"TimeControlEvaluator: {'Available' if time_control_evaluator else 'Not Available (schedule alerts disabled)'}"
        )
        logger.info(f"Total Devices: {total_devices}")
        logger.info(f"Total Alerts: {total_alerts}")
        logger.info(f"Skipped Devices: {skipped_devices}")

    def evaluate(self, device_id: str, snapshot: dict[str, float]) -> list[tuple[str, str, AlertSeverity, str]]:
        """
        Evaluate alerts for a device snapshot.

        Returns:
            List of (alert_code, message, severity, notification_type)
        """
        result_list: list[tuple[str, str, AlertSeverity, str]] = []

        try:
            # Safely split device_id into model and slave_id
            # e.g. "TECO_VFD_2" → ("TECO_VFD", "2")
            model, slave_id = device_id.rsplit("_", 1)
        except ValueError:
            logger.warning(f"[SKIP] Invalid device_id format: {device_id}")
            return result_list

        model_alerts: dict[str, list[AlertConditionModel]] = self.device_alert_dict.get(model, {})
        alert_list: list[AlertConditionModel] | None = model_alerts.get(slave_id)
        if not alert_list:
            logger.info(f"No alert config for device_id: {device_id}")
            return result_list

        for alert in alert_list:
            # Route to different evaluation logic based on alert type
            if isinstance(alert, ScheduleExpectedStateAlertConfig):
                # Time-based expected state evaluation
                evaluation_result: tuple[bool, float] | None = self._evaluate_schedule_expected_state(
                    alert, snapshot, device_id
                )
            elif isinstance(alert, (ThresholdAlertConfig, AggregateAlertConfig)):
                # Traditional threshold/aggregate evaluation
                evaluation_result: tuple[bool, float] | None = self._evaluate_threshold_or_aggregate(
                    alert, snapshot, device_id
                )
            else:
                logger.warning(f"[{device_id}] Unknown alert type: {type(alert)}")
                continue

            if evaluation_result is None:
                continue  # Unable to evaluate, skip

            triggered, alert_value = evaluation_result

            # Check if notification should be sent
            should_notify, notification_type = self.state_manager.should_notify(
                device_id=device_id,
                alert_code=alert.code,
                is_triggered=triggered,
                severity=alert.severity,
                current_value=alert_value,
            )

            if should_notify:
                # Build notification message
                msg = self._build_notification_message(
                    alert=alert,
                    alert_value=alert_value,
                    notification_type=notification_type,
                )
                result_list.append((alert.code, msg, alert.severity, notification_type))

        return result_list

    def _calculate_alert_value(
        self, alert: AlertConditionModel, snapshot: dict[str, float], device_id: str
    ) -> float | None:
        """
        Calculate alert value based on type (threshold or aggregate).

        Args:
            alert: Alert condition configuration
            snapshot: Device snapshot data
            device_id: Device identifier for logging

        Returns:
            Calculated value or None if unable to calculate
        """
        # Collect values from all sources
        values = []
        missing_sources = []

        for source in alert.sources:
            if source not in snapshot:
                missing_sources.append(source)
                continue
            values.append(snapshot[source])

        # Check if all required sources are available
        if missing_sources:
            logger.warning(f"[{device_id}] Alert '{alert.code}': " f"Missing sources {missing_sources} in snapshot")
            return None

        if not values:
            logger.warning(f"[{device_id}] Alert '{alert.code}': No values collected")
            return None

        # Calculate based on type
        try:
            match alert.type:

                case ConditionType.THRESHOLD:
                    # Single source
                    return values[0]

                case ConditionType.AVERAGE:
                    return sum(values) / len(values)

                case ConditionType.SUM:
                    return sum(values)

                case ConditionType.MIN:
                    return min(values)

                case ConditionType.MAX:
                    return max(values)

                case _:
                    logger.warning(f"[{device_id}] Unknown alert type: {alert.type}")
                    return None

        except Exception as e:
            logger.error(f"[{device_id}] Error calculating {alert.type.value} " f"for alert '{alert.code}': {e}")
            return None

    def _evaluate_schedule_expected_state(
        self,
        alert: ScheduleExpectedStateAlertConfig,
        snapshot: dict[str, float],
        device_id: str,
    ) -> tuple[bool, float] | None:
        """
        Evaluate schedule-based expected state alert.

        Logic:
        1. Check if current time is within work_hours (via TimeControlEvaluator)
        2. If in work_hours → no alert (device is allowed to run)
        3. If outside work_hours (shutdown period) → check actual vs expected state

        Returns:
            (triggered: bool, actual_state_value: float) or None if unable to evaluate
        """
        # Check if TimeControlEvaluator is available
        if self.time_control_evaluator is None:
            logger.warning(
                f"[{device_id}] Alert '{alert.code}': TimeControlEvaluator not available, "
                f"cannot evaluate schedule_expected_state alert"
            )
            return None

        # Get actual device state from snapshot
        source = alert.sources[0]  # Already validated to have exactly 1 source
        if source not in snapshot:
            logger.warning(f"[{device_id}] Alert '{alert.code}': " f"Source '{source}' not found in snapshot")
            return None

        actual_state = snapshot[source]

        # Check if current time is within work_hours
        is_in_work_hours: bool = self.time_control_evaluator.allow(device_id)

        if is_in_work_hours:
            # Device is allowed to run, no alert
            logger.debug(f"[{device_id}] Alert '{alert.code}': " f"In work_hours, device allowed to run")
            return (False, actual_state)

        # Outside work_hours (shutdown period), check expected vs actual state
        expected_state = alert.expected_state
        triggered = actual_state != expected_state

        if triggered:
            logger.info(
                f"[{device_id}] Alert '{alert.code}': "
                f"Outside work_hours, actual_state={actual_state} != expected_state={expected_state}"
            )
        else:
            logger.debug(
                f"[{device_id}] Alert '{alert.code}': " f"Outside work_hours, state matches expected ({expected_state})"
            )

        return (triggered, actual_state)

    def _evaluate_threshold_or_aggregate(
        self,
        alert: ThresholdAlertConfig | AggregateAlertConfig,
        snapshot: dict[str, float],
        device_id: str,
    ) -> tuple[bool, float] | None:
        """
        Evaluate traditional threshold or aggregate alert.

        Returns:
            (triggered: bool, calculated_value: float) or None if unable to evaluate
        """
        # Calculate alert value (supports both threshold and aggregate types)
        alert_value = self._calculate_alert_value(alert, snapshot, device_id)
        if alert_value is None:
            return None  # Unable to calculate value

        # Evaluate condition
        triggered: bool = False

        match alert.condition:
            case ConditionOperator.GREATER_THAN:
                triggered = alert_value > alert.threshold
            case ConditionOperator.LESS_THAN:
                triggered = alert_value < alert.threshold
            case ConditionOperator.EQUAL:
                triggered = alert_value == alert.threshold
            case ConditionOperator.GREATER_THAN_OR_EQUAL:
                triggered = alert_value >= alert.threshold
            case ConditionOperator.LESS_THAN_OR_EQUAL:
                triggered = alert_value <= alert.threshold
            case ConditionOperator.NOT_EQUAL:
                triggered = alert_value != alert.threshold
            case _:
                logger.warning(f"[{device_id}] Unknown operator: {alert.condition}")
                return None

        return (triggered, alert_value)

    def _build_notification_message(
        self,
        alert: AlertConditionModel,
        alert_value: float,
        notification_type: str,
    ) -> str:
        """
        Build notification message based on alert type and notification type.

        Args:
            alert: Alert configuration
            alert_value: Current value that triggered the alert
            notification_type: "TRIGGERED" or "RESOLVED"

        Returns:
            Formatted notification message
        """
        # Build sources display string
        sources_str = ", ".join(alert.sources)
        if isinstance(alert, ScheduleExpectedStateAlertConfig):
            # Schedule expected state: show source and actual state
            sources_display = f"{sources_str}"
        elif len(alert.sources) > 1:
            # Multi-source: show aggregate type
            sources_display = f"{alert.type.value}({sources_str})"
        else:
            # Single source: just show source name
            sources_display = sources_str

        # Build message based on notification type and alert type
        if notification_type == AlertState.TRIGGERED.name:
            if isinstance(alert, ScheduleExpectedStateAlertConfig):
                # Schedule expected state message
                state_text = "ON" if alert_value == 1 else "OFF"
                expected_text = "ON" if alert.expected_state == 1 else "OFF"
                msg = (
                    f"[{alert.severity.value}] {alert.name}: "
                    f"{sources_display}={state_text} (expected {expected_text}) "
                    f"during shutdown period"
                )
            else:
                # Threshold/aggregate message
                msg = (
                    f"[{alert.severity.value}] {alert.name}: "
                    f"{sources_display}={alert_value:.2f} violates "
                    f"{alert.condition.value} {alert.threshold}"
                )

        elif notification_type == AlertState.RESOLVED.name:
            if isinstance(alert, ScheduleExpectedStateAlertConfig):
                # Schedule expected state resolved
                state_text = "ON" if alert_value == 1 else "OFF"
                msg = f"[RESOLVED] {alert.name}: " f"{sources_display}={state_text} returned to expected state"
            else:
                # Threshold/aggregate resolved
                msg = (
                    f"[RESOLVED] {alert.name}: "
                    f"{sources_display}={alert_value:.2f} returned to normal "
                    f"(threshold: {alert.threshold})"
                )
        else:
            logger.warning(f"Unknown notification_type: {notification_type}")
            msg = f"[{alert.severity.value}] {alert.name}: Unknown notification type"

        return msg
