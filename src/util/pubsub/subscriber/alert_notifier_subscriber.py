import logging

from schema.alert_schema import AlertMessageModel
from util.notifier.base import BaseNotifier
from util.pubsub.base import PubSub
from util.pubsub.pubsub_topic import PubSubTopic


class AlertNotifierSubscriber:
    def __init__(self, pubsub: PubSub, notifier_list: list[BaseNotifier]):
        self.pubsub = pubsub
        self.notifier_list = notifier_list
        self.logger = logging.getLogger(__class__.__name__)

    async def run(self):
        async for alert in self.pubsub.subscribe(PubSubTopic.ALERT_WARNING):
            if not isinstance(alert, AlertMessageModel):
                self.logger.warning(f"[SKIP] Invalid alert object: {alert}")
                continue

            for notifier in self.notifier_list:
                try:
                    await notifier.send(alert)
                except Exception as e:
                    self.logger.warning(f"[{notifier.__class__.__name__}] Failed to send: {e}")
