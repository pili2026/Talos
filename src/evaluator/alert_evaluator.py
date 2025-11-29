import logging

from alert_config import AlertConfig
from evaluator.alert_state_manager import AlertStateManager
from model.enum.alert_enum import AlertSeverity
from model.enum.alert_state_enum import AlertState
from model.enum.condition_enum import ConditionOperator, ConditionType
from schema.alert_schema import AlertConditionModel

logger = logging.getLogger("AlertEvaluator")


class AlertEvaluator:
    def __init__(self, alert_config: AlertConfig, valid_device_ids: set[str]):
        # Nest struct: { model: { slave_id: [AlertConditionModel] } }
        self.device_alert_dict: dict[str, dict[str, list[AlertConditionModel]]] = {}

        for model, model_config in alert_config.root.items():
            self.device_alert_dict[model] = {}

            for slave_id in model_config.instances:
                device_id = f"{model}_{slave_id}"

                if device_id not in valid_device_ids:
                    logger.warning(f"[SKIP] Unknown device in config: {device_id}")
                    continue

                alerts = alert_config.get_instance_alerts(model, slave_id)
                if alerts:
                    self.device_alert_dict[model][slave_id] = alerts
                else:
                    logger.info(f"[{device_id}] No alert configured. Skipped.")

        self.state_manager = AlertStateManager()

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

        model_alerts = self.device_alert_dict.get(model, {})
        alert_list = model_alerts.get(slave_id)
        if not alert_list:
            logger.debug(f"No alert config for device_id: {device_id}")
            return result_list

        for alert in alert_list:
            # Calculate alert value (supports both threshold and aggregate types)
            alert_value = self._calculate_alert_value(alert, snapshot, device_id)
            if alert_value is None:
                continue  # Unable to calculate value, skip this alert

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
                    continue

            # Check if notification should be sent
            should_notify, notification_type = self.state_manager.should_notify(
                device_id=device_id,
                alert_code=alert.code,
                is_triggered=triggered,
                severity=alert.severity,
                current_value=alert_value,
            )

            if should_notify:
                # Build message with sources information
                sources_str = ", ".join(alert.sources)
                if len(alert.sources) > 1:
                    # Multi-source: show aggregate type
                    sources_display = f"{alert.type.value}({sources_str})"
                else:
                    # Single source: just show source name
                    sources_display = sources_str

                if notification_type == AlertState.TRIGGERED.name:
                    msg = (
                        f"[{alert.severity.value}] {alert.name}: "
                        f"{sources_display}={alert_value:.2f} violates "
                        f"{alert.condition.value} {alert.threshold}"
                    )
                elif notification_type == AlertState.RESOLVED.name:
                    msg = (
                        f"[RESOLVED] {alert.name}: "
                        f"{sources_display}={alert_value:.2f} returned to normal "
                        f"(threshold: {alert.threshold})"
                    )
                else:
                    logger.warning(f"[{device_id}] Unknown notification_type: {notification_type}")
                    continue  # Should not happen

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
