"""Service layer for snapshot data operations."""

import logging
from datetime import datetime, timedelta

from api.model.snapshot_responses import (
    CleanupResponse,
    DatabaseStatsResponse,
    RecentSnapshotsResponse,
    SnapshotHistoryResponse,
    SnapshotResponse,
)
from core.util.time_util import TIMEZONE_INFO
from repository.snapshot_repository import SnapshotRepository

logger = logging.getLogger(__name__)


class SnapshotService:
    """
    Snapshot Service Layer

    Responsibilities:
    - Query coordination and parameter filtering
    - Data transformation between Repository and API layers
    - Business logic for snapshot operations
    """

    def __init__(self, snapshot_repo: SnapshotRepository):
        self._snapshot_repo = snapshot_repo

    async def get_device_history(
        self,
        device_id: str,
        start_time: datetime,
        end_time: datetime,
        parameters: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,  # ← 新增 pagination
    ) -> SnapshotHistoryResponse:
        """
        Get device snapshot history with optional parameter filtering and pagination.

        Args:
            device_id: Device identifier
            start_time: Query start time (inclusive)
            end_time: Query end time (inclusive)
            parameters: Optional list of parameter names to include
            limit: Maximum number of snapshots to return per page
            offset: Number of snapshots to skip (for pagination)

        Returns:
            SnapshotHistoryResponse with filtered and paginated data
        """
        # Fetch paginated data from repository
        snapshots_dict = await self._snapshot_repo.get_time_range(
            device_id=device_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset,
        )

        # Filter parameters if specified
        if parameters:
            for snapshot in snapshots_dict:
                values = snapshot.get("values", {})
                filtered_values = {k: v for k, v in values.items() if k in parameters}
                snapshot["values"] = filtered_values

        # Convert to response models
        snapshots = [SnapshotResponse(**s) for s in snapshots_dict]

        # Get total count for pagination metadata
        total_count = await self._snapshot_repo.get_count_in_time_range(
            device_id=device_id,
            start_time=start_time,
            end_time=end_time,
        )

        return SnapshotHistoryResponse(
            device_id=device_id,
            start_time=start_time,
            end_time=end_time,
            snapshots=snapshots,
            total_count=total_count,
            limit=limit,
            offset=offset,
        )

    async def get_latest_snapshot(
        self,
        device_id: str,
        parameters: list[str] | None = None,
    ) -> SnapshotResponse | None:
        """
        Get the most recent snapshot for a device.

        Args:
            device_id: Device identifier
            parameters: Optional list of parameter names to include

        Returns:
            Latest snapshot or None if not found
        """
        snapshots_dict = await self._snapshot_repo.get_latest_by_device(device_id=device_id, limit=1)

        if not snapshots_dict:
            return None

        snapshot_dict = snapshots_dict[0]

        # Filter parameters if specified
        if parameters:
            values = snapshot_dict.get("values", {})
            filtered_values = {k: v for k, v in values.items() if k in parameters}
            snapshot_dict["values"] = filtered_values

        return SnapshotResponse(**snapshot_dict)

    async def get_recent_snapshots(
        self,
        minutes: int = 10,
        parameters: list[str] | None = None,
    ) -> RecentSnapshotsResponse:
        """
        Get recent snapshots across all devices.

        Args:
            minutes: Time window in minutes
            parameters: Optional parameter filter

        Returns:
            Recent snapshots from all devices
        """
        snapshots_dict = await self._snapshot_repo.get_all_recent(minutes=minutes)

        # Filter parameters if specified
        if parameters:
            for snapshot in snapshots_dict:
                values = snapshot.get("values", {})
                filtered_values = {k: v for k, v in values.items() if k in parameters}
                snapshot["values"] = filtered_values

        snapshots = [SnapshotResponse(**s) for s in snapshots_dict]

        return RecentSnapshotsResponse(
            minutes=minutes,
            snapshots=snapshots,
            total_count=len(snapshots),
        )

    async def get_database_stats(self) -> DatabaseStatsResponse:
        """
        Get snapshot database statistics.

        Returns:
            Database stats including size and record counts
        """
        stats = await self._snapshot_repo.get_db_stats()
        return DatabaseStatsResponse(**stats)

    async def cleanup_old_snapshots(self, retention_days: int) -> CleanupResponse:
        """
        Delete snapshots older than specified days.

        Args:
            retention_days: Keep snapshots newer than this

        Returns:
            Cleanup operation result
        """
        deleted_count = await self._snapshot_repo.cleanup_old_snapshots(retention_days=retention_days)

        cutoff_time = datetime.now(tz=TIMEZONE_INFO) - timedelta(days=retention_days)

        return CleanupResponse(
            deleted_count=deleted_count,
            retention_days=retention_days,
            cutoff_time=cutoff_time,
            status="success" if deleted_count >= 0 else "error",
        )

    async def vacuum_database(self) -> dict[str, str]:
        """
        Run VACUUM to reclaim disk space.

        Returns:
            Operation status
        """
        try:
            await self._snapshot_repo.vacuum_database()
            return {"status": "success", "message": "Database vacuumed successfully"}
        except Exception as e:
            logger.error(f"VACUUM failed: {e}")
            return {"status": "error", "message": str(e)}
