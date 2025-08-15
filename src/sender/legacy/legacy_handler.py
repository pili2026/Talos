import logging

from sender.legacy.legacy_sender import LegacySenderAdapter
from util.pubsub.subscriber.sender_subscriber import SnapshotHandler

logger = logging.getLogger("LegacySnapshotHandler")


class LegacySnapshotHandler(SnapshotHandler):
    def __init__(self, sender: LegacySenderAdapter):
        self.sender = sender

    async def handle_snapshot(self, snapshot: dict):
        await self.sender.handle_snapshot(snapshot)
