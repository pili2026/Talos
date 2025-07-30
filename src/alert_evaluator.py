import logging

from model.alert_model import AlertConditionModel, AlertConfig
from model.condition_enum import ConditionOperator

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

    def evaluate(self, device_id: str, snapshot: dict[str, float]) -> list[tuple[str, str]]:
        result_list: list[tuple[str, str]] = []

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
            triggered = False

            match alert.condition:
                case ConditionOperator.GREATER_THAN:
                    triggered = pin_value > alert.threshold
                case ConditionOperator.LESS_THAN:
                    triggered = pin_value < alert.threshold
                case ConditionOperator.EQUAL:
                    triggered = pin_value == alert.threshold
                case _:
                    logger.warning(f"[{device_id}] Unknown operator: {alert.condition}")

            if triggered:
                msg = (
                    f"[{alert.severity}] {alert.name}: "
                    f"{alert.source}={pin_value:.2f} violates {alert.condition} {alert.threshold}"
                )
                result_list.append((alert.code, msg))

        return result_list
