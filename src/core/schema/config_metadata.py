"""
Configuration Metadata Schema for Talos
Provides unified metadata tracking for all configuration files
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from enum import Enum

import yaml
from pydantic import BaseModel, Field, field_validator

from core.util.time_util import TIMEZONE_INFO

logger = logging.getLogger(__name__)


class ConfigSource(str, Enum):
    """Source of configuration change"""

    CLOUD = "cloud"
    EDGE = "edge"
    MANUAL = "manual"


class ConfigMetadata(BaseModel):
    """
    Unified metadata for all configuration files.
    Enables version tracking, conflict detection, and audit trail.
    """

    generation: int = Field(
        default=1,
        ge=1,
        description="Monotonically increasing version number for conflict detection",
    )

    config_source: ConfigSource = Field(
        default=ConfigSource.EDGE,
        description="Origin of this configuration (cloud/edge/manual)",
    )

    last_modified: str = Field(
        default_factory=lambda: datetime.now(TIMEZONE_INFO).isoformat(),
        description="Last modification timestamp (ISO 8601 UTC)",
    )

    last_modified_by: str | None = Field(
        default=None,
        description="User/system that made the modification (email/user_id/system)",
    )

    checksum: str | None = Field(
        default=None,
        description="SHA256 checksum of configuration content (excluding metadata)",
    )

    applied_at: str | None = Field(
        default=None,
        description="Timestamp when edge actually applied the configuration (ISO 8601 UTC)",
    )

    cloud_sync_id: str | None = Field(
        default=None,
        description="Cloud-side configuration identifier for tracking",
    )

    @field_validator("last_modified", "applied_at", mode="before")
    @classmethod
    def validate_iso_datetime(cls, v: str | None) -> str | None:
        """Validate and normalize ISO 8601 datetime strings"""
        if v is None:
            return None

        # Handle string input
        if not isinstance(v, str):
            logger.warning(f"[config_metadata] Invalid datetime type: {type(v)}, converting to now")
            return datetime.now(TIMEZONE_INFO).isoformat()

        try:
            # Parse ISO 8601 (handle 'Z' suffix)
            datetime.fromisoformat(v.replace("Z", "+00:00"))
            return v
        except ValueError:
            logger.warning(f"[config_metadata] Invalid ISO datetime: {v!r}, using now")
            return datetime.now(TIMEZONE_INFO).isoformat()

    @field_validator("generation", mode="before")
    @classmethod
    def validate_generation(cls, v: int | None) -> int:
        """Ensure generation is valid positive integer"""
        if v is None:
            return 1

        try:
            gen = int(v)
            if gen < 1:
                logger.warning(f"[config_metadata] Invalid generation: {gen}, using 1")
                return 1
            return gen
        except (ValueError, TypeError):
            logger.warning(f"[config_metadata] Invalid generation type: {v!r}, using 1")
            return 1


def calculate_config_checksum(config_data: dict) -> str:
    """
    Calculate SHA256 checksum of configuration data.
    Excludes metadata to avoid circular dependency.

    Args:
        config_data: Configuration dictionary (should not include _metadata key)

    Returns:
        Checksum string in format "sha256:..."
    """
    # Remove metadata if present
    data_copy: dict = config_data.copy()
    data_copy.pop("_metadata", None)
    data_copy.pop("metadata", None)

    # Convert to YAML with sorted keys for consistency
    yaml_content: str = yaml.dump(data_copy, sort_keys=True, allow_unicode=True, default_flow_style=False)

    # Calculate hash
    hash_obj = hashlib.sha256(yaml_content.encode("utf-8"))
    return f"sha256:{hash_obj.hexdigest()}"


def increment_generation(current_metadata: ConfigMetadata) -> int:
    """
    Safely increment generation number.

    Args:
        current_metadata: Current metadata object

    Returns:
        Next generation number
    """
    return current_metadata.generation + 1
