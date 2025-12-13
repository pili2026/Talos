"""Subscriber for saving device snapshots to SQLite database."""

import logging

from core.util.pubsub.base import PubSub
from core.util.pubsub.pubsub_topic import PubSubTopic
from repository.snapshot_repository import SnapshotRepository

logger = logging.getLogger(__name__)


class SnapshotSaverSubscriber:
    """
    Subscriber that listens to DEVICE_SNAPSHOT events and persists them to SQLite.

    Runs independently and does not block other subscribers on errors.
    """

    def __init__(self, pubsub: PubSub, repository: SnapshotRepository):
        """
        Initialize the snapshot saver subscriber.

        Args:
            pubsub: PubSub instance for event subscription
            repository: SnapshotRepository for data persistence
        """
        self.pubsub = pubsub
        self.repository = repository

    async def run(self) -> None:
        """
        Main loop: subscribe to DEVICE_SNAPSHOT and save to database.

        Errors are logged but not propagated to ensure resilience.
        """
        logger.info("SnapshotSaverSubscriber started")

        async for snapshot in self.pubsub.subscribe(PubSubTopic.DEVICE_SNAPSHOT):
            try:
                await self.handle_snapshot(snapshot)
            except Exception as e:
                # Error isolation: log but don't crash
                logger.exception(
                    f"[SnapshotSaver] Failed to save snapshot for "
                    f"device_id={snapshot.get('device_id', 'UNKNOWN')}: {e}"
                )

    async def handle_snapshot(self, snapshot: dict) -> None:
        """
        Handle a single snapshot event.

        Args:
            snapshot: Snapshot dictionary from DeviceMonitor with keys:
                - device_id: str
                - model: str
                - slave_id: str
                - type: str
                - sampling_ts: datetime
                - values: dict
        """
        # Insert snapshot immediately
        await self.repository.insert_snapshot(snapshot)

        logger.debug(f"[SnapshotSaver] Saved snapshot for device_id={snapshot['device_id']}")
