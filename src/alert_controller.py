class AlertEvaluator:
    def __init__(self, alert_config: dict):
        self.alerts = alert_config.get("alerts", [])

    def evaluate(self, snapshot: dict) -> list[str]:
        """
        snapshot: {
            "AIn01": 25.3,
            "AIn02": 20.0,
            ...
        }
        Return: list of alert messages triggered
        """
        messages = []
        for alert in self.alerts:
            alert_type = alert["type"]
            if alert_type == "difference":
                inputs = alert["inputs"]
                threshold = alert["threshold"]
                val1 = snapshot.get(inputs[0])
                val2 = snapshot.get(inputs[1])
                if val1 is not None and val2 is not None:
                    diff = abs(val1 - val2)
                    if diff > threshold:
                        messages.append(
                            f"[{alert['severity'].upper()}] {alert['name']}: Delta T={diff:.2f} ({inputs[0]}={val1:.2f}, {inputs[1]}={val2:.2f})"
                        )
        return messages
