import logging

from core.sender.legacy.legacy_sender import LegacySenderAdapter
from core.util.pubsub.subscriber.sender_subscriber import SnapshotHandler

logger = logging.getLogger("LegacySnapshotHandler")


class LegacySnapshotHandler(SnapshotHandler):
    def __init__(self, sender: LegacySenderAdapter):
        self.sender = sender

    async def handle_snapshot(self, snapshot: dict):
        await self.sender.handle_snapshot(snapshot)
