import logging
from typing import Protocol, Sequence

from core.util.pubsub.base import PubSub
from core.util.pubsub.pubsub_topic import PubSubTopic

logger = logging.getLogger("SenderSubscriber")


class SnapshotHandler(Protocol):
    async def handle_snapshot(self, snapshot: dict) -> None: ...


class SenderSubscriber:
    def __init__(self, pubsub: PubSub, handlers: Sequence[SnapshotHandler]):
        self.pubsub = pubsub
        self.handlers = handlers

    async def run(self):
        async for snapshot in self.pubsub.subscribe(PubSubTopic.DEVICE_SNAPSHOT):
            for handler in self.handlers:
                try:
                    await handler.handle_snapshot(snapshot)
                except Exception as e:
                    logger.exception("[SenderSubscriber] Handler failed: %s", e)
