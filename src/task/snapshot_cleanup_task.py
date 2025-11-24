"""Background task for snapshot database maintenance."""

import asyncio
import logging
from datetime import datetime

from repository.snapshot_repository import SnapshotRepository

logger = logging.getLogger(__name__)


class SnapshotCleanupTask:
    """
    Background task for snapshot database maintenance.

    Performs two types of maintenance:
    1. DELETE old snapshots (periodic cleanup based on retention policy)
    2. VACUUM database (periodic space reclamation)
    """

    def __init__(
        self,
        repository: SnapshotRepository,
        db_path: str,
        retention_days: int = 7,
        cleanup_interval_hours: int = 6,
        vacuum_interval_days: int = 7,
    ):
        """
        Initialize the cleanup task.

        Args:
            repository: SnapshotRepository instance
            db_path: Path to database file (for stats)
            retention_days: Keep data for N days (default: 7)
            cleanup_interval_hours: Run DELETE every N hours (default: 6)
            vacuum_interval_days: Run VACUUM every N days (default: 7)
        """
        self.repository = repository
        self.db_path = db_path
        self.retention_days = retention_days
        self.cleanup_interval_hours = cleanup_interval_hours
        self.vacuum_interval_days = vacuum_interval_days

        self.cleanup_interval_seconds = cleanup_interval_hours * 3600
        self.vacuum_interval_seconds = vacuum_interval_days * 86400

        self.last_vacuum_time: datetime | None = None

    async def run(self) -> None:
        """
        Main background loop.

        Runs cleanup operations on schedule:
        - DELETE: every cleanup_interval_hours
        - VACUUM: every vacuum_interval_days
        """
        logger.info(
            f"SnapshotCleanupTask started: "
            f"retention={self.retention_days}d, "
            f"cleanup_interval={self.cleanup_interval_hours}h, "
            f"vacuum_interval={self.vacuum_interval_days}d"
        )

        # Run initial cleanup after a short delay
        await asyncio.sleep(60)  # Wait 1 minute before first cleanup

        while True:
            try:
                await self._run_cleanup_cycle()
            except Exception as e:
                logger.exception(f"[SnapshotCleanup] Error during cleanup cycle: {e}")

            # Wait for next cleanup interval
            await asyncio.sleep(self.cleanup_interval_seconds)

    async def _run_cleanup_cycle(self) -> None:
        """Run one cleanup cycle (DELETE + optional VACUUM)."""
        logger.info("[SnapshotCleanup] Starting cleanup cycle...")

        # 1. Delete old snapshots
        deleted_count = await self.repository.cleanup_old_snapshots(self.retention_days)

        # 2. Get database stats
        stats = await self.repository.get_db_stats(self.db_path)
        logger.info(
            f"[SnapshotCleanup] DB stats: "
            f"total={stats['total_count']}, "
            f"size={stats['file_size_mb']}MB, "
            f"earliest={stats['earliest_ts']}, "
            f"latest={stats['latest_ts']}"
        )

        # 3. Run VACUUM if needed
        if self._should_run_vacuum():
            logger.info("[SnapshotCleanup] Running VACUUM...")
            await self.repository.vacuum_database()
            self.last_vacuum_time = datetime.utcnow()
            logger.info("[SnapshotCleanup] VACUUM completed")
        else:
            if self.last_vacuum_time:
                next_vacuum = self.last_vacuum_time.timestamp() + self.vacuum_interval_seconds
                hours_until_vacuum = (next_vacuum - datetime.utcnow().timestamp()) / 3600
                logger.debug(f"[SnapshotCleanup] Next VACUUM in {hours_until_vacuum:.1f} hours")

        logger.info(f"[SnapshotCleanup] Cleanup cycle completed (deleted {deleted_count} records)")

    def _should_run_vacuum(self) -> bool:
        """
        Check if VACUUM should be run.

        Returns:
            True if VACUUM should run, False otherwise
        """
        if self.last_vacuum_time is None:
            return True

        elapsed_seconds = (datetime.utcnow() - self.last_vacuum_time).total_seconds()
        return elapsed_seconds >= self.vacuum_interval_seconds
