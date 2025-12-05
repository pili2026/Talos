"""Response models for snapshot API endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field


class SnapshotResponse(BaseModel):
    """Single snapshot response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: str
    model: str
    slave_id: str
    device_type: str
    sampling_ts: datetime
    created_at: datetime
    values: dict[str, Any]
    is_online: int


class SnapshotHistoryResponse(BaseModel):
    """Device snapshot history with pagination metadata."""

    device_id: str
    start_time: datetime
    end_time: datetime
    snapshots: list[SnapshotResponse]
    total_count: int = Field(description="Total number of snapshots in time range")
    limit: int = Field(description="Number of records per page")
    offset: int = Field(description="Number of records skipped")

    @computed_field
    @property
    def has_next(self) -> bool:
        """Check if there are more records available."""
        return self.offset + len(self.snapshots) < self.total_count

    @computed_field
    @property
    def has_previous(self) -> bool:
        """Check if there are previous records."""
        return self.offset > 0

    @computed_field
    @property
    def page_number(self) -> int:
        """Calculate current page number (1-indexed)."""
        if self.limit == 0:
            return 1
        return (self.offset // self.limit) + 1

    @computed_field
    @property
    def total_pages(self) -> int:
        """Calculate total number of pages."""
        if self.limit == 0:
            return 1
        return (self.total_count + self.limit - 1) // self.limit

    @computed_field
    @property
    def next_offset(self) -> int | None:
        """Get offset for next page, or None if no next page."""
        if not self.has_next:
            return None
        return self.offset + self.limit

    @computed_field
    @property
    def previous_offset(self) -> int | None:
        """Get offset for previous page, or None if no previous page."""
        if not self.has_previous:
            return None
        return max(0, self.offset - self.limit)


class RecentSnapshotsResponse(BaseModel):
    """Recent snapshots across all devices."""

    minutes: int = Field(description="Time window in minutes")
    snapshots: list[SnapshotResponse]
    total_count: int


class DatabaseStatsResponse(BaseModel):
    """Snapshot database statistics."""

    total_count: int = Field(description="Total number of snapshots")
    earliest_ts: datetime | None = Field(description="Oldest snapshot timestamp")
    latest_ts: datetime | None = Field(description="Newest snapshot timestamp")
    file_size_bytes: int
    file_size_mb: float
    devices: dict[str, int] | None = Field(
        default=None,
        description="Snapshot count per device",
    )


class CleanupResponse(BaseModel):
    """Cleanup operation result."""

    deleted_count: int
    retention_days: int
    cutoff_time: datetime
    status: str = "success"
