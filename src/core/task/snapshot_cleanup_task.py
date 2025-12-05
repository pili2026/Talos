import logging
from datetime import datetime
from typing import Any

from core.task.async_job_base import AsyncRecurringJob
from core.util.time_util import TIMEZONE_INFO
from repository.snapshot_repository import SnapshotRepository

logger = logging.getLogger(__name__)


class SnapshotCleanupTask(AsyncRecurringJob):
    """
    Recurring background job that maintains the snapshot SQLite database.

    Responsibilities:
        - Periodically delete old snapshot records (based on retention days)
        - Periodically run VACUUM to rebuild and shrink the SQLite file
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
        Args:
            repository: SnapshotRepository for DB operations
            db_path: Path to SQLite database file
            retention_days: Delete snapshots older than this
            cleanup_interval_hours: How often run cleanup cycles
            vacuum_interval_days: How often run VACUUM operations
        """
        self.repository = repository
        self.db_path = db_path
        self.retention_days = int(retention_days)

        self.vacuum_interval_days = int(vacuum_interval_days)
        self.vacuum_interval_seconds = self.vacuum_interval_days * 86400

        self.last_vacuum_time: datetime | None = None

        # Initialize recurring interval using the base class
        super().__init__(interval_seconds=cleanup_interval_hours * 3600)

    # ----------------------------------------------------------------------
    # Required logic per cycle
    # ----------------------------------------------------------------------
    async def run_once(self) -> None:
        """
        Execute a single maintenance cycle:
        - delete old snapshots
        - gather DB statistics
        - perform VACUUM if needed
        """
        logger.info("[SnapshotCleanup] Starting cleanup cycle...")

        # 1. Delete expired snapshots
        deleted_count: int = await self.repository.cleanup_old_snapshots(self.retention_days)

        # 2. Read DB statistics
        stats: dict[str, Any] = await self.repository.get_db_stats()

        logger.info(
            f"[SnapshotCleanup] DB stats: "
            f"total={stats['total_count']}, "
            f"size={stats['file_size_mb']}MB, "
            f"earliest={stats['earliest_ts']}, "
            f"latest={stats['latest_ts']}"
        )

        # 3. Determine whether VACUUM should be executed
        if self._should_run_vacuum():
            logger.info("[SnapshotCleanup] Performing VACUUM...")
            await self.repository.vacuum_database()
            self.last_vacuum_time = datetime.now(tz=TIMEZONE_INFO)
            logger.info("[SnapshotCleanup] VACUUM completed")

        logger.info(f"[SnapshotCleanup] Cleanup cycle completed (deleted {deleted_count} records)")

    # ----------------------------------------------------------------------
    # Helper
    # ----------------------------------------------------------------------
    def _should_run_vacuum(self) -> bool:
        """
        Check whether VACUUM should run based on the last run time.

        Returns:
            True if VACUUM should be executed, otherwise False.
        """
        if self.last_vacuum_time is None:
            return True

        elapsed_seconds: float = (datetime.now(tz=TIMEZONE_INFO) - self.last_vacuum_time).total_seconds()
        return elapsed_seconds >= self.vacuum_interval_seconds
