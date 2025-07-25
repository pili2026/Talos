import logging

from model.alert_model import AlertConditionModel, AlertConfig
from model.condition_enum import ConditionOperator

logger = logging.getLogger("AlertEvaluator")


class AlertEvaluator:
    def __init__(self, alert_config: AlertConfig, valid_device_ids: set[str]):

        self.device_alert_dict: dict[str, list[AlertConditionModel]] = {}

        for model, model_config in alert_config.root.items():
            for slave_id in model_config.instances:

                if model not in valid_device_ids:
                    logger.warning(f"[SKIP] Alert config found for unknown device: {model}")
                    continue

                alerts = alert_config.get_instance_alerts(model, slave_id)
                if alerts:
                    self.device_alert_dict[model] = alerts
                else:
                    logger.info(f"[{model}] No alert configured. Skipped.")

    def evaluate(self, model: str, snapshot: dict[str, float]) -> list[tuple[str, str]]:
        result_list: list[tuple[str, str]] = []

        alert_list: list[AlertConditionModel] | None = self.device_alert_dict.get(model)
        if not alert_list:
            logger.debug(f"No alert config found for '{model}'")
            return result_list

        for alert in alert_list:
            if alert.source not in snapshot:
                logger.warning(f"[{model}] Pin '{alert.source}' not in snapshot")
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
                case _:
                    logger.warning(f"[{model}] Unknown condition operator: {alert.condition}")

            if triggered:
                msg = (
                    f"[{alert.severity}] {alert.name}: "
                    f"{alert.source}={pin_value:.2f} violates {alert.condition} {alert.threshold}"
                )
                result_list.append((alert.code, msg))

        return result_list
