import logging

logger = logging.getLogger("AlertEvaluator")


class AlertEvaluator:
    def __init__(self, alert_config: dict):
        self.device_alert_map: dict[str, dict] = alert_config

    def evaluate(self, device_id: str, snapshot: dict[str, float], pins: dict[str, dict]) -> list[tuple[str, str]]:
        results = []

        device_config = self.device_alert_map.get(device_id)
        if not device_config:
            logger.warning(f"[AlertEvaluator] No alert config for device_id: '{device_id}'")
            return results

        alerts = device_config.get("alerts", [])
        if not alerts:
            logger.info(f"[AlertEvaluator] No alerts defined for device '{device_id}'")
            return results

        for alert in alerts:
            if alert.get("type") != "threshold":
                continue

            pin_name = alert.get("pin")
            if not pin_name or pin_name not in snapshot:
                continue

            pin_value = snapshot[pin_name]
            condition = alert.get("condition", "gt")
            threshold = alert.get("threshold")
            severity = alert.get("severity", "info").upper()
            name = alert.get("name", "Unnamed Alert")
            code = alert.get("code", "UNKNOWN_ALERT")

            triggered = False
            if condition == "gt":
                triggered = pin_value > threshold
            elif condition == "lt":
                triggered = pin_value < threshold
            elif condition == "eq":
                triggered = pin_value == threshold

            if triggered:
                msg = f"[{severity}] {name}: {pin_name}={pin_value:.2f} violates condition {condition} {threshold}"
                results.append((code, msg))

        return results
