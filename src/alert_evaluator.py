import logging

from model.alert_model import AlertConditionModel, AlertConfig
from model.condition_enum import ConditionOperator

logger = logging.getLogger("AlertEvaluator")


class AlertEvaluator:
    def __init__(self, alert_config: AlertConfig):
        self.device_alert_dict: dict[str, list[AlertConditionModel]] = {}

        for model, model_config in alert_config.root.items():
            for slave_id in model_config.instances.keys():
                device_id = f"{model}_{slave_id}"
                alert_list: list[AlertConditionModel] = alert_config.get_instance_alerts(model, slave_id)
                if alert_list:
                    self.device_alert_dict[device_id] = alert_list
                else:
                    logger.info(f"[{device_id}] No alert configured. Skipped.")

    def evaluate(self, device_id: str, snapshot: dict[str, float]) -> list[tuple[str, str]]:
        results: list[tuple[str, str]] = []

        alert_list: list[AlertConditionModel] | None = self.device_alert_dict.get(device_id)
        if not alert_list:
            logger.debug(f"No alert config found for '{device_id}'")
            return results

        for alert in alert_list:
            if alert.source not in snapshot:
                logger.warning(f"[{device_id}] Pin '{alert.source}' not in snapshot")
                continue

            pin_value = snapshot[alert.source]
            triggered = False

            match alert.condition:
                case ConditionOperator.GREATER_THAN:
                    triggered = pin_value > alert.threshold
                case ConditionOperator.LESS_THAN:
                    triggered = pin_value < alert.threshold
                case ConditionOperator.EQUAL:
                    triggered = pin_value == alert.threshold

            if triggered:
                msg = (
                    f"[{alert.severity}] {alert.name}: "
                    f"{alert.source}={pin_value:.2f} violates {alert.condition} {alert.threshold}"
                )
                results.append((alert.code, msg))

        return results
