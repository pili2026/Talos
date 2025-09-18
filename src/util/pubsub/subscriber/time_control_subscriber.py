import logging

from handler.time_control_handler import TimeControlHandler
from util.pubsub.base import PubSub
from util.pubsub.pubsub_topic import PubSubTopic

logger = logging.getLogger("TimeControlSubscriber")


class TimeControlSubscriber:
    def __init__(self, pubsub: PubSub, time_control_handler: TimeControlHandler):
        self.pubsub = pubsub
        self.handler = time_control_handler

    async def run(self):
        async for snapshot in self.pubsub.subscribe(PubSubTopic.DEVICE_SNAPSHOT):
            await self.handler.handle_snapshot(snapshot)
