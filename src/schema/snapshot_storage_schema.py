"""Configuration schema for snapshot storage."""

from pydantic import BaseModel, Field


class SnapshotStorageConfig(BaseModel):
    """
    Configuration for SQLite snapshot storage.

    Controls whether snapshot persistence is enabled and
    defines retention and maintenance policies.
    """

    enabled: bool = Field(
        default=True,
        description="Enable/disable snapshot storage to SQLite",
    )

    db_path: str = Field(
        default="/home/talos/data/snapshots.db",
        description="Path to SQLite database file",
    )

    # Retention policy
    retention_days: int = Field(
        default=7,
        ge=1,
        description="Number of days to retain snapshot data",
    )

    cleanup_interval_hours: int = Field(
        default=6,
        ge=1,
        description="How often to run cleanup (delete old snapshots), in hours",
    )

    vacuum_interval_days: int = Field(
        default=7,
        ge=1,
        description="How often to run VACUUM (reclaim disk space), in days",
    )

    class Config:
        """Pydantic config."""

        extra = "allow"  # Allow extra fields for future extensions
