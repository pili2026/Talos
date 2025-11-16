import logging

from alert_config import AlertConfig
from evaluator.alert_state_manager import AlertStateManager
from model.enum.alert_enum import AlertSeverity
from model.enum.alert_state_enum import AlertState
from model.enum.condition_enum import ConditionOperator
from schema.alert_schema import AlertConditionModel

logger = logging.getLogger("AlertEvaluator")


class AlertEvaluator:
    def __init__(self, alert_config: AlertConfig, valid_device_ids: set[str]):
        # Nest struct：{ model: { slave_id: [AlertConditionModel] } }
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
        result_list: list[tuple[str, str, AlertSeverity, str]] = []

        try:
            # Safely split a device_id string into model and slave_id parts.
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
            if alert.source not in snapshot:
                logger.warning(f"[{device_id}] Pin '{alert.source}' not in snapshot")
                continue

            pin_value = snapshot[alert.source]
            triggered: bool = False

            match alert.condition:
                case ConditionOperator.GREATER_THAN:
                    triggered = pin_value > alert.threshold
                case ConditionOperator.LESS_THAN:
                    triggered = pin_value < alert.threshold
                case ConditionOperator.EQUAL:
                    triggered = pin_value == alert.threshold
                case ConditionOperator.GREATER_THAN_OR_EQUAL:
                    triggered = pin_value >= alert.threshold
                case ConditionOperator.LESS_THAN_OR_EQUAL:
                    triggered = pin_value <= alert.threshold
                case ConditionOperator.NOT_EQUAL:
                    triggered = pin_value != alert.threshold
                case _:
                    logger.warning(f"[{device_id}] Unknown operator: {alert.condition}")
                    continue

            should_notify, notification_type = self.state_manager.should_notify(
                device_id=device_id,
                alert_code=alert.code,
                is_triggered=triggered,
                severity=alert.severity,
                current_value=pin_value,
            )

            if should_notify:
                if notification_type == AlertState.TRIGGERED.name:
                    msg = (
                        f"[{alert.severity}] {alert.name}: "
                        f"{alert.source}={pin_value:.2f} violates {alert.condition} {alert.threshold}"
                    )
                elif notification_type == AlertState.RESOLVED.name:
                    msg = (
                        f"[RESOLVED] {alert.name}: "
                        f"{alert.source}={pin_value:.2f} returned to normal (threshold: {alert.threshold})"
                    )
                else:
                    logger.warning(f"[{device_id}] Unknown notification_type: {notification_type}")
                    continue  # Should not happen

                result_list.append((alert.code, msg, alert.severity, notification_type))

        return result_list
