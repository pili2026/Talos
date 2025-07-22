import logging

logger = logging.getLogger("AlertEvaluator")


class AlertEvaluator:
    def __init__(self, alert_config: dict):
        self.device_alert_map: dict[str, dict] = alert_config

    def evaluate(self, device_id: str, snapshot: dict[str, float]) -> list[tuple[str, str]]:
        results = []

        # TODO:
        device_config: dict | None = self.device_alert_map.get(device_id)
        if not device_config:
            logger.warning(f"No alert config found for '{device_id}'")
            return results

        alerts: list = device_config.get("alerts", [])
        for alert in alerts:
            if alert.get("type") != "threshold":
                continue

            pin_name: str = alert.get("pin")
            if not pin_name:
                logger.warning(f"[{device_id}] Alert missing 'pin' field: {alert}")
                continue

            if pin_name not in snapshot:
                logger.warning(f"[{device_id}] Pin '{pin_name}' not in snapshot")
                continue

            pin_value = snapshot[pin_name]
            condition = alert.get("condition", "gt")
            threshold = alert.get("threshold")
            severity = alert.get("severity", "info").upper()
            name = alert.get("name", "Unnamed Alert")
            code = alert.get("code", "UNKNOWN_ALERT")

            triggered = (
                (condition == "gt" and pin_value > threshold)
                or (condition == "lt" and pin_value < threshold)
                or (condition == "eq" and pin_value == threshold)
            )

            if triggered:
                msg = f"[{severity}] {name}: " f"{pin_name}={pin_value:.2f} violates condition {condition} {threshold}"
                results.append((code, msg))

        return results
