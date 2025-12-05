"""SQLAlchemy model for device snapshot storage."""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from core.util.time_util import TIMEZONE_INFO


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""

    ...


class Snapshot(Base):
    """
    Device snapshot model for SQLite storage.

    Stores complete device snapshots with their metadata and values.
    Indexed for efficient querying by device, timestamp, and type.
    """

    __tablename__ = "snapshots"

    # Primary key
    # wait to confirm if autoincrement is needed
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Device identification
    device_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(50), nullable=False)
    slave_id: Mapped[str] = mapped_column(String(50), nullable=False)
    device_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Timestamps
    sampling_ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(tz=TIMEZONE_INFO)
    )

    # Snapshot data (stored as JSON string)
    values_json: Mapped[str] = mapped_column(Text, nullable=False)

    # Communication status (1=online, 0=offline)
    is_online: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Composite indexes for efficient queries
    __table_args__ = (
        Index("idx_device_ts", "device_id", "sampling_ts"),
        Index("idx_ts", "sampling_ts"),
        Index("idx_type", "device_type"),
    )

    def __repr__(self) -> str:
        return (
            f"<Snapshot(id={self.id}, device_id={self.device_id}, "
            f"sampling_ts={self.sampling_ts}, is_online={self.is_online})>"
        )
