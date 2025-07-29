import logging

from util.notifier.base import BaseNotifier
from util.pubsub.base import PubSub
from util.pubsub.pubsub_topic import PubSubTopic


class AlertSubscriber:
    def __init__(self, pubsub: PubSub, notifier_list: list[BaseNotifier]):
        self.pubsub = pubsub
        self.notifier_list = notifier_list
        self.logger = logging.getLogger("AlertSubscriber")

    async def run(self):
        async for alert in self.pubsub.subscribe(PubSubTopic.ALERT_WARNING):
            for notifier in self.notifier_list:
                try:
                    await notifier.send(alert)
                except Exception as e:
                    self.logger.warning(f"[{notifier.__class__.__name__}] Failed to send: {e}")
