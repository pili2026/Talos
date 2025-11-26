"""Repository for snapshot data access operations."""

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, desc, func, select, text

from repository.model.snapshot_model import Snapshot
from util.db_manager import SQLiteSnapshotDBManager
from util.time_util import TIMEZONE_INFO

logger = logging.getLogger(__name__)


class SnapshotRepository:
    """
    Repository for managing device snapshot persistence.
    Uses SQLiteSnapshotDBManager instead of raw AsyncEngine.
    """

    def __init__(self, db_manager: SQLiteSnapshotDBManager):
        """
        Args:
            db_manager: SQLite DB manager (wrapper for engine & session)
        """
        self.db = db_manager

    async def init_db(self) -> None:
        """Initialize database schema."""
        await self.db.init_database()
        logger.info("Snapshot database initialized")

    # --------------------------------------------------------------
    # INSERT
    # --------------------------------------------------------------
    async def insert_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Insert a single snapshot into SQLite."""

        value_dict: dict = snapshot.get("values", {})
        numeric_value_list: list[int | float] = [v for v in value_dict.values() if isinstance(v, (int, float))]
        is_online: int = 1 if not all(v == -1 for v in numeric_value_list) else 0

        record = Snapshot(
            device_id=snapshot["device_id"],
            model=snapshot["model"],
            slave_id=str(snapshot["slave_id"]),
            device_type=snapshot["type"],
            sampling_ts=snapshot["sampling_ts"],
            created_at=datetime.now(tz=TIMEZONE_INFO),
            values_json=json.dumps(value_dict),
            is_online=is_online,
        )

        async with self.db.get_async_session() as session:
            session.add(record)
            await session.commit()

        logger.debug(
            f"[Snapshot] Inserted device={snapshot['device_id']} " f"ts={snapshot['sampling_ts']} online={is_online}"
        )

    # --------------------------------------------------------------
    # QUERIES
    # --------------------------------------------------------------
    async def get_latest_by_device(self, device_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Fetch latest snapshots for a device."""
        async with self.db.get_async_session() as session:
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
        self, device_id: str, start_time: datetime, end_time: datetime, limit: int = 1000, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Query snapshots in a time range with pagination support."""
        async with self.db.get_async_session() as session:
            stmt = (
                select(Snapshot)
                .where(
                    Snapshot.device_id == device_id,
                    Snapshot.sampling_ts >= start_time,
                    Snapshot.sampling_ts <= end_time,
                )
                .order_by(Snapshot.sampling_ts)
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(stmt)
            snapshots = result.scalars().all()

        logger.debug(
            f"[Snapshot] Query {device_id}: {start_time} to {end_time}, "
            f"limit={limit}, offset={offset}, returned={len(snapshots)}"
        )

        return [self._snapshot_to_dict(s) for s in snapshots]

    async def get_count_in_time_range(self, device_id: str, start_time: datetime, end_time: datetime) -> int:
        """
        Get total count of snapshots in time range (for pagination metadata).

        This query is optimized to use the composite index (device_id, sampling_ts).
        """
        async with self.db.get_async_session() as session:
            stmt = select(func.count(Snapshot.id)).where(
                Snapshot.device_id == device_id,
                Snapshot.sampling_ts >= start_time,
                Snapshot.sampling_ts <= end_time,
            )
            result = await session.execute(stmt)
            count = result.scalar() or 0

        logger.debug(f"[Snapshot] Count {device_id}: {start_time} to {end_time}, total={count}")

        return count

    async def get_parameter_history(
        self, device_id: str, parameter: str, start_time: datetime, end_time: datetime, limit: int = 1000
    ) -> list[dict[str, Any]]:
        """Return history of a single parameter using json_extract()."""
        json_path = f"$.{parameter}"

        async with self.db.get_async_session() as session:
            stmt = text(
                """
                SELECT
                    sampling_ts,
                    json_extract(values_json, :json_path) AS value,
                    is_online
                FROM snapshots
                WHERE device_id = :device_id
                  AND sampling_ts >= :start_time
                  AND sampling_ts <= :end_time
                ORDER BY sampling_ts ASC
                LIMIT :limit
                """
            )

            r = await session.execute(
                stmt,
                {
                    "json_path": json_path,
                    "device_id": device_id,
                    "start_time": start_time,
                    "end_time": end_time,
                    "limit": limit,
                },
            )

            rows = r.fetchall()

        return [{"sampling_ts": row[0], "value": row[1], "is_online": row[2]} for row in rows]

    async def get_all_recent(self, minutes: int) -> list[dict[str, Any]]:
        """Fetch all snapshots in the last N minutes."""
        cutoff = datetime.now(tz=TIMEZONE_INFO) - timedelta(minutes=minutes)

        async with self.db.get_async_session() as session:
            stmt = select(Snapshot).where(Snapshot.sampling_ts >= cutoff).order_by(desc(Snapshot.sampling_ts))
            result = await session.execute(stmt)
            snapshots = result.scalars().all()

        return [self._snapshot_to_dict(s) for s in snapshots]

    # --------------------------------------------------------------
    # MAINTENANCE
    # --------------------------------------------------------------
    async def cleanup_old_snapshots(self, retention_days: int) -> int:
        """Delete snapshots older than N days."""
        cutoff = datetime.now(tz=TIMEZONE_INFO) - timedelta(days=retention_days)

        async with self.db.get_async_session() as session:
            stmt = delete(Snapshot).where(Snapshot.sampling_ts < cutoff)
            result = await session.execute(stmt)
            await session.commit()
            deleted = result.rowcount

        logger.info(f"Deleted {deleted} old snapshots (> {retention_days}d)")
        return deleted

    async def vacuum_database(self) -> None:
        """Run VACUUM."""
        logger.info("Running VACUUM...")
        async with self.db.async_engine.begin() as conn:
            await conn.execute(text("VACUUM"))
        logger.info("VACUUM completed")

    async def get_db_stats(self) -> dict[str, Any]:
        """Return size, earliest/latest timestamp, record count."""
        async with self.db.get_async_session() as session:
            # Count
            count_stmt = select(func.count(Snapshot.id))
            count = (await session.execute(count_stmt)).scalar() or 0

            if count > 0:
                earliest = (await session.execute(select(func.min(Snapshot.sampling_ts)))).scalar()
                latest = (await session.execute(select(func.max(Snapshot.sampling_ts)))).scalar()
            else:
                earliest = None
                latest = None

        file_bytes = self.db.get_file_size()

        return {
            "total_count": count,
            "earliest_ts": earliest,
            "latest_ts": latest,
            "file_size_bytes": file_bytes,
            "file_size_mb": round(file_bytes / (1024 * 1024), 2),
        }

    # --------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------
    def _snapshot_to_dict(self, s: Snapshot) -> dict[str, Any]:
        return {
            "id": s.id,
            "device_id": s.device_id,
            "model": s.model,
            "slave_id": s.slave_id,
            "device_type": s.device_type,
            "sampling_ts": s.sampling_ts,
            "created_at": s.created_at,
            "values": json.loads(s.values_json),
            "is_online": s.is_online,
        }
