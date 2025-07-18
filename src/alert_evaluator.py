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
