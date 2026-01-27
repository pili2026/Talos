"""
Source configuration schema for multi-device data aggregation.

This module defines the Source model used in v2.0 control condition design,
supporting hierarchical data aggregation from multiple devices.
"""

import logging

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.model.enum.condition_enum import AggregationType

logger = logging.getLogger(__name__)


class Source(BaseModel):
    """
    Data source definition for control conditions.

    Represents a single data source that can aggregate values from multiple pins
    on a specific device.

    Examples:
        Single pin from device:
        >>> Source(device="ADAM-4117", slave_id="12", pins=["AIn01"])

        Multiple pins with aggregation:
        >>> Source(
        ...     device="ADAM-4117",
        ...     slave_id="12",
        ...     pins=["AIn01", "AIn02", "AIn03"],
        ...     aggregation="average"
        ... )
    """

    model_config = ConfigDict(
        str_strip_whitespace=True, validate_assignment=True, extra="forbid"  # Reject unknown fields
    )

    device: str = Field(
        ...,
        description="Device model name (e.g., 'ADAM-4117', 'TECO_VFD')",
        examples=["ADAM-4117", "TECO_VFD", "ADTEK_CPM10"],
    )

    slave_id: str = Field(
        ..., description="Device slave ID (always string for consistency)", examples=["1", "12", "14"]
    )

    pins: list[str] = Field(
        ...,
        description="List of pin/register names to read from this device",
        examples=[["AIn01"], ["AIn01", "AIn02", "AIn03"], ["HZ", "RW_HZ"]],
    )

    aggregation: AggregationType | None = Field(
        default=None,
        description=(
            "Aggregation method for multiple pins. "
            "If None and multiple pins specified, defaults to 'average'. "
            "Ignored if only one pin specified."
        ),
        examples=[AggregationType.AVERAGE, AggregationType.SUM, AggregationType.MAX],
    )

    @field_validator("device", "slave_id")
    @classmethod
    def validate_non_empty(cls, v: str, info) -> str:
        """Ensure device and slave_id are non-empty after stripping"""
        if not v or not v.strip():
            field_name = info.field_name
            raise ValueError(f"{field_name} cannot be empty")
        return v.strip()

    @field_validator("device", "slave_id", mode="before")
    @classmethod
    def coerce_to_str(cls, v):
        """Coerce device/slave_id to string (allow numeric slave_id)"""
        if v is None:
            return v
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, str)):
            return str(v)
        return v

    @field_validator("pins")
    @classmethod
    def validate_pins_unique(cls, v: list[str]) -> list[str]:
        """Ensure pins list contains unique values"""
        if not v:
            raise ValueError("pins list cannot be empty")

        # Strip and filter empty strings
        cleaned = [p.strip() for p in v if p.strip()]

        if not cleaned:
            raise ValueError("pins list cannot contain only empty strings")

        # Check uniqueness
        if len(cleaned) != len(set(cleaned)):
            duplicates = [p for p in cleaned if cleaned.count(p) > 1]
            raise ValueError(f"pins list contains duplicates: {set(duplicates)}")

        return cleaned

    def get_effective_aggregation(self) -> AggregationType | None:
        """
        Get the effective aggregation method.

        Returns:
            - None if single pin (no aggregation needed)
            - Specified aggregation method if multiple pins
            - "average" if multiple pins but no aggregation specified (default)
        """
        if len(self.pins) == 1:
            return None  # Single pin, no aggregation needed

        return self.aggregation or AggregationType.AVERAGE  # Multi-pin: use specified or default

    def __str__(self) -> str:
        """Human-readable representation"""
        pins_str: str = ",".join(self.pins)
        aggregation: AggregationType | None = self.get_effective_aggregation()

        if aggregation:
            return f"{self.device}_{self.slave_id}:[{pins_str}]({aggregation.value})"
        return f"{self.device}_{self.slave_id}:{pins_str}"

    def __repr__(self) -> str:
        return (
            f"Source(device={self.device}, slave_id={self.slave_id}, pins={self.pins}, aggregation={self.aggregation})"
        )
