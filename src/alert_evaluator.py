import logging

logger = logging.getLogger("AlertEvaluator")


class AlertEvaluator:
    def __init__(self, alert_config: dict):
        self.model_alert_map: dict[str, list[dict]] = {
            model: config.get("alerts", []) for model, config in alert_config.items()
        }

    def evaluate(self, model: str, snapshot: dict[str, float], pins: dict[str, dict]) -> list[tuple[str, str]]:
        results = []

        alerts = self.model_alert_map.get(model)
        if alerts is None:
            logger.warning(f"[AlertEvaluator] No alert config found for model: '{model}'")
            return results

        for alert in alerts:
            alert_type = alert.get("type")
            threshold = alert.get("threshold")
            severity = alert.get("severity", "info").upper()
            name = alert.get("name", "Unnamed Alert")
            code = alert.get("code", "UNKNOWN_ALERT")

            if alert_type == "threshold":
                for pin_name, pin_value in snapshot.items():
                    pin_meta = pins.get(pin_name, {})
                    if pin_meta.get("type") != "thermometer":
                        continue

                    if pin_value > threshold:
                        msg = f"[{severity}] {name}: {pin_name}={pin_value:.2f} exceeds threshold {threshold}"
                        results.append((code, msg))

        return results
