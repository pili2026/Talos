import logging

from model.alert_message import AlertMessage
from util.pubsub.base import PubSub


class EmailNotifier:
    def __init__(self, pubsub: PubSub):
        self.pubsub = pubsub
        self.logger = logging.getLogger("EmailNotifier")

    async def run(self):
        async for alert in self.pubsub.subscribe("alert.warning"):
            await self.send_email(alert)

    async def send_email(self, alert: AlertMessage):
        # Mock email logic — just print for now
        self.logger.info(f"Sending mock email: [{alert.level}] {alert.device_id} - {alert.message}")
