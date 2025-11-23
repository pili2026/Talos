"""Repository for snapshot data access operations."""

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from db.engine import create_session_factory, get_db_file_size, init_database
from model.snapshot_model import Snapshot

logger = logging.getLogger(__name__)


class SnapshotRepository:
    """
    Repository for managing device snapshot persistence.

    Provides async methods for CRUD operations, queries, and maintenance.
    """

    def __init__(self, engine: AsyncEngine):
        """
        Initialize the repository.

        Args:
            engine: SQLAlchemy AsyncEngine instance
        """
        self.engine = engine
        self.session_factory = create_session_factory(engine)

    async def init_db(self) -> None:
        """Initialize database schema (create tables if not exist)."""
        await init_database(self.engine)
        logger.info("Snapshot database initialized")

    async def insert_snapshot(self, snapshot: dict[str, Any]) -> None:
        """
        Insert a single snapshot into the database.

        Args:
            snapshot: Snapshot dictionary with keys:
                - device_id: str
                - model: str
                - slave_id: str
                - type: str (device_type)
                - sampling_ts: datetime
                - values: dict (snapshot values)

        Note:
            is_online is automatically determined:
            - If all numeric values are -1 → offline (communication failure)
            - Otherwise → online (normal or partial sensor failure)
        """
        # Determine online status
        values = snapshot.get("values", {})
        numeric_values = [v for v in values.values() if isinstance(v, (int, float))]
        is_online = 1 if not all(v == -1 for v in numeric_values) else 0

        # Create snapshot record
        snapshot_record = Snapshot(
            device_id=snapshot["device_id"],
            model=snapshot["model"],
            slave_id=str(snapshot["slave_id"]),
            device_type=snapshot["type"],
            sampling_ts=snapshot["sampling_ts"],
            created_at=datetime.utcnow(),
            values_json=json.dumps(values),
            is_online=is_online,
        )

        async with self.session_factory() as session:
            session.add(snapshot_record)
            await session.commit()

        logger.debug(
            f"Inserted snapshot: device_id={snapshot['device_id']}, "
            f"sampling_ts={snapshot['sampling_ts']}, is_online={is_online}"
        )

    async def get_latest_by_device(self, device_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """
        Get latest N snapshots for a specific device.

        Args:
            device_id: Device identifier
            limit: Maximum number of snapshots to return

        Returns:
            List of snapshot dictionaries (most recent first)
        """
        async with self.session_factory() as session:
            stmt = (
                select(Snapshot)
                .where(Snapshot.device_id == device_id)
                .order_by(desc(Snapshot.sampling_ts))
                .limit(limit)
            )
            result = await session.execute(stmt)
            snapshots = result.scalars().all()

        return [self._snapshot_to_dict(s) for s in snapshots]

    async def get_time_range(
        self,
        device_id: str,
        start_time: datetime,
        end_time: datetime,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """
        Query snapshots within a time range for a device.

        Args:
            device_id: Device identifier
            start_time: Start of time range (inclusive)
            end_time: End of time range (inclusive)
            limit: Maximum number of snapshots to return

        Returns:
            List of snapshot dictionaries (ordered by time ascending)
        """
        async with self.session_factory() as session:
            stmt = (
                select(Snapshot)
                .where(
                    Snapshot.device_id == device_id,
                    Snapshot.sampling_ts >= start_time,
                    Snapshot.sampling_ts <= end_time,
                )
                .order_by(Snapshot.sampling_ts)
                .limit(limit)
            )
            result = await session.execute(stmt)
            snapshots = result.scalars().all()

        return [self._snapshot_to_dict(s) for s in snapshots]

    async def get_parameter_history(
        self,
        device_id: str,
        parameter: str,
        start_time: datetime,
        end_time: datetime,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """
        Query history of a specific parameter for a device.

        Uses SQLite JSON functions to extract parameter from values_json.

        Args:
            device_id: Device identifier
            parameter: Parameter name (e.g., 'AIn01', 'HZ')
            start_time: Start of time range
            end_time: End of time range
            limit: Maximum number of records to return

        Returns:
            List of dictionaries with keys:
                - sampling_ts: datetime
                - value: parameter value (can be None if not present)
                - is_online: int
        """
        async with self.session_factory() as session:
            # Use SQLite JSON extraction: json_extract(values_json, '$.parameter')
            json_path = f"$.{parameter}"
            stmt = text(
                """
                SELECT
                    sampling_ts,
                    json_extract(values_json, :json_path) as value,
                    is_online
                FROM snapshots
                WHERE device_id = :device_id
                  AND sampling_ts >= :start_time
                  AND sampling_ts <= :end_time
                ORDER BY sampling_ts ASC
                LIMIT :limit
                """
            )

            result = await session.execute(
                stmt,
                {
                    "json_path": json_path,
                    "device_id": device_id,
                    "start_time": start_time,
                    "end_time": end_time,
                    "limit": limit,
                },
            )

            rows = result.fetchall()

        return [
            {
                "sampling_ts": row[0],
                "value": row[1],
                "is_online": row[2],
            }
            for row in rows
        ]

    async def get_all_recent(self, minutes: int) -> list[dict[str, Any]]:
        """
        Get all snapshots from all devices in the last N minutes.

        Args:
            minutes: Number of minutes to look back

        Returns:
            List of snapshot dictionaries
        """
        cutoff_time = datetime.utcnow() - timedelta(minutes=minutes)

        async with self.session_factory() as session:
            stmt = (
                select(Snapshot)
                .where(Snapshot.sampling_ts >= cutoff_time)
                .order_by(desc(Snapshot.sampling_ts))
            )
            result = await session.execute(stmt)
            snapshots = result.scalars().all()

        return [self._snapshot_to_dict(s) for s in snapshots]

    async def cleanup_old_snapshots(self, retention_days: int) -> int:
        """
        Delete snapshots older than retention period.

        Args:
            retention_days: Number of days to retain data

        Returns:
            Number of snapshots deleted
        """
        cutoff_time = datetime.utcnow() - timedelta(days=retention_days)

        async with self.session_factory() as session:
            stmt = delete(Snapshot).where(Snapshot.sampling_ts < cutoff_time)
            result = await session.execute(stmt)
            await session.commit()
            deleted_count = result.rowcount

        logger.info(f"Cleaned up {deleted_count} snapshots older than {retention_days} days")
        return deleted_count

    async def vacuum_database(self) -> None:
        """
        Execute VACUUM to reclaim disk space.

        Note: This operation can take time on large databases.
        Should be run during low-traffic periods.
        """
        logger.info("Starting VACUUM operation...")
        async with self.engine.begin() as conn:
            await conn.execute(text("VACUUM"))
        logger.info("VACUUM operation completed")

    async def get_db_stats(self, db_path: str) -> dict[str, Any]:
        """
        Get database statistics.

        Args:
            db_path: Path to the database file

        Returns:
            Dictionary with statistics:
                - total_count: Total number of snapshots
                - earliest_ts: Earliest sampling timestamp
                - latest_ts: Latest sampling timestamp
                - file_size_bytes: Database file size in bytes
                - file_size_mb: Database file size in MB
        """
        async with self.session_factory() as session:
            # Get total count
            count_stmt = select(func.count(Snapshot.id))
            count_result = await session.execute(count_stmt)
            total_count = count_result.scalar() or 0

            # Get earliest and latest timestamps
            if total_count > 0:
                earliest_stmt = select(func.min(Snapshot.sampling_ts))
                earliest_result = await session.execute(earliest_stmt)
                earliest_ts = earliest_result.scalar()

                latest_stmt = select(func.max(Snapshot.sampling_ts))
                latest_result = await session.execute(latest_stmt)
                latest_ts = latest_result.scalar()
            else:
                earliest_ts = None
                latest_ts = None

        # Get file size
        file_size_bytes = await get_db_file_size(db_path)

        return {
            "total_count": total_count,
            "earliest_ts": earliest_ts,
            "latest_ts": latest_ts,
            "file_size_bytes": file_size_bytes,
            "file_size_mb": round(file_size_bytes / (1024 * 1024), 2),
        }

    def _snapshot_to_dict(self, snapshot: Snapshot) -> dict[str, Any]:
        """
        Convert Snapshot model to dictionary.

        Args:
            snapshot: Snapshot model instance

        Returns:
            Dictionary representation
        """
        return {
            "id": snapshot.id,
            "device_id": snapshot.device_id,
            "model": snapshot.model,
            "slave_id": snapshot.slave_id,
            "device_type": snapshot.device_type,
            "sampling_ts": snapshot.sampling_ts,
            "created_at": snapshot.created_at,
            "values": json.loads(snapshot.values_json),
            "is_online": snapshot.is_online,
        }
