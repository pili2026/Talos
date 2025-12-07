"""Factory for building snapshot storage subscriber."""

import logging

from core.util.config_manager import ConfigManager
from core.util.pubsub.base import PubSub
from core.util.pubsub.subscriber.snapshot_saver_subscriber import SnapshotSaverSubscriber
from repository.schema.snapshot_storage_schema import SnapshotStorageConfig
from repository.snapshot_repository import SnapshotRepository
from repository.util.db_manager import SQLiteSnapshotDBManager

logger = logging.getLogger(__name__)


async def build_snapshot_subscriber(
    snapshot_config_path: str,
    pubsub: PubSub,
) -> tuple[SnapshotSaverSubscriber | None, SnapshotRepository | None, SQLiteSnapshotDBManager | None]:
    """
    Build snapshot saver subscriber, repository, and DB manager.

    Args:
        snapshot_config_path: Path to snapshot storage config file
        pubsub: PubSub instance for event subscription

    Returns:
        Tuple of (subscriber, repository, db_manager):
        - (SnapshotSaverSubscriber, SnapshotRepository, SQLiteSnapshotDBManager) if enabled
        - (None, None, None) if disabled

    Raises:
        Exception: If database initialization fails

    Examples:
        >>> # Main.py usage (needs repository for cleanup task)
        >>> sub, repo, db = await build_snapshot_subscriber(
        ...     "res/snapshot_storage.yml",
        ...     pubsub
        ... )
        >>> if sub:
        ...     cleanup_task = SnapshotCleanupTask(repository=repo, ...)

        >>> # main_with_api.py usage (only needs subscriber)
        >>> sub, _, _ = await build_snapshot_subscriber(...)
        >>> if sub:
        ...     subscriber_registry.register("SNAPSHOT_SAVER", sub.run)
    """
    # Load and validate config
    snapshot_storage_raw = ConfigManager.load_yaml_file(snapshot_config_path)
    snapshot_storage = SnapshotStorageConfig(**snapshot_storage_raw)

    if not snapshot_storage.enabled:
        logger.info("Snapshot storage is disabled")
        return None, None, None

    logger.info(
        f"Initializing snapshot storage: "
        f"retention={snapshot_storage.retention_days}d, "
        f"db={snapshot_storage.db_path}"
    )

    try:
        # Initialize DB manager
        db_manager = SQLiteSnapshotDBManager(
            db_path=snapshot_storage.db_path,
            echo=False,
        )

        # Wait for DB availability and initialize schema
        await db_manager.wait_for_db_available()
        await db_manager.init_database()

        logger.info("Database initialized")

        # Create repository (single shared instance)
        repository = SnapshotRepository(db_manager)

        # Create subscriber
        subscriber = SnapshotSaverSubscriber(pubsub, repository)

        logger.info("Snapshot subscriber created")

        return subscriber, repository, db_manager

    except Exception as e:
        logger.error(f"Failed to initialize snapshot storage: {e}", exc_info=True)
        raise
