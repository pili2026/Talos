import logging
import time
from collections import defaultdict

from model.alert_message import AlertMessage
from util.pubsub.base import PubSub


class EmailNotifier:
    def __init__(self, pubsub: PubSub, threshold_sec: float = 60.0):
        self.pubsub = pubsub
        self.logger = logging.getLogger("EmailNotifier")
        self.threshold_sec = threshold_sec
        self.last_sent: dict[tuple[str, str], float] = defaultdict(lambda: 0.0)

    async def run(self):
        async for alert in self.pubsub.subscribe("alert.warning"):
            await self.send_email(alert)

    async def send_email(self, alert: AlertMessage):
        key = (alert.device_key, alert.message)
        now = time.time()

        # Check if the alert is within the threshold
        if now - self.last_sent[key] < self.threshold_sec:
            self.logger.info(f"Skip Duplicate Alert Notification: [{alert.device_key}] {alert.message}")
            return

        self.last_sent[key] = now

        self.logger.info(f"Send Email: [{alert.level}] {alert.device_key} - {alert.message}")
