import logging

from model.alert_model import AlertConditionModel
from model.condition_enum import ConditionOperator

logger = logging.getLogger("AlertEvaluator")


class AlertEvaluator:
    def __init__(self, alert_config: dict):
        self.device_alert_dict: dict[str, list[AlertConditionModel]] = {}

        for device_id, config in alert_config.items():
            alerts = config.get("alerts", [])
            valid_alerts = []
            for alert_dict in alerts:
                try:
                    alert = AlertConditionModel(**alert_dict)
                    if alert.type == "threshold":
                        valid_alerts.append(alert)
                except Exception as e:
                    logger.warning(f"[{device_id}] Skipping invalid alert config: {alert_dict} -> {e}")
            self.device_alert_dict[device_id] = valid_alerts

    def evaluate(self, device_id: str, snapshot: dict[str, float]) -> list[tuple[str, str]]:
        results = []

        alert_list: list[AlertConditionModel] | None = self.device_alert_dict.get(device_id)
        if not alert_list:
            logger.debug(f"No alert config found for '{device_id}'")
            return results

        for alert in alert_list:
            if alert.source not in snapshot:
                logger.warning(f"[{device_id}] Pin '{alert.source}' not in snapshot")
                continue

            pin_value = snapshot[alert.source]

            match alert.condition:
                case ConditionOperator.GREATER_THAN:
                    triggered = pin_value > alert.threshold
                case ConditionOperator.LESS_THAN:
                    triggered = pin_value < alert.threshold
                case ConditionOperator.EQUAL:
                    triggered = pin_value == alert.threshold
                case _:
                    triggered = False

            if triggered:
                msg = (
                    f"[{alert.severity}] {alert.name}: "
                    f"{alert.source}={pin_value:.2f} violates {alert.condition} {alert.threshold}"
                )
                results.append((alert.code, msg))

        return results
