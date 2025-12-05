"""Configuration schema for snapshot storage."""

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SnapshotStorageConfig(BaseModel):
    """
    Configuration for SQLite snapshot storage.

    Controls whether snapshot persistence is enabled and
    defines retention and maintenance policies.
    """

    model_config = ConfigDict(
        extra="allow",  # Allow extra fields for future extensions
    )

    enabled: bool = Field(
        default=True,
        description="Enable/disable snapshot storage to SQLite",
    )

    db_path: str = Field(
        default="",
        description="Path to SQLite database file. Leave empty for auto-selection.",
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

    @field_validator("db_path", mode="before")
    @classmethod
    def resolve_db_path(cls, v: str | None) -> str:
        """
        Resolve database path with priority:
        1. Environment variable TALOS_DATA_DIR (for Docker)
        2. YAML db_path (if specified)
        3. Default ./data/snapshots.db (for development)
        """
        # 1. Environment variable (Docker/production)
        env_data_dir = os.getenv("TALOS_DATA_DIR")
        if env_data_dir:
            path = Path(env_data_dir) / "snapshots.db"
            return str(path.resolve())

        # 2. YAML specified path
        if v:
            return str(Path(v).expanduser().resolve())

        # 3. Default development path
        default_path = Path("./data/snapshots.db")
        return str(default_path.resolve())
