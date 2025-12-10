"""
Virtual Device Configuration Schema

Defines Pydantic models for virtual device configuration.
Virtual devices aggregate data from multiple physical devices.

Example configuration:
    virtual_devices:
      - id: "loop0_power_summary"
        enabled: true
        type: "aggregated_power_meter"
        source:
          model: "ADTEK_CPM10"
          slave_ids: [1, 2]  # Optional: None or [] = all devices
        target:
          model: "ADTEK_CPM10"
          slave_id: "auto"  # "auto" = max(all_slave_ids) + 1
        aggregation:
          error_handling: "fail_fast"
          fields:
            - name: "Kw"
              method: "sum"
            - name: "AverageVoltage"
              method: "avg"
            - name: "AveragePowerFactor"
              method: "calculated_pf"
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.model.enum.condition_enum import ConditionType


class AggregationMethod(StrEnum):
    """Method for aggregating field values across source devices"""

    SUM = ConditionType.SUM.value
    AVG = ConditionType.AVERAGE.value
    MIN = ConditionType.MIN.value
    MAX = ConditionType.MAX.value
    CALCULATED_PF = "calculated_pf"  # Special: Power Factor = Kw / Kva


class ErrorHandling(StrEnum):
    """Strategy for handling read failures from source devices"""

    FAIL_FAST = "fail_fast"  # If any source fails (-1), result is -1
    PARTIAL = "partial"  # Use only successful reads (future implementation)


class AggregatedFieldConfig(BaseModel):
    """Configuration for a single aggregated field"""

    name: str = Field(..., description="Field name to aggregate (e.g., 'Kw', 'Phase_A_Current')")
    method: AggregationMethod = Field(..., description="Aggregation method (sum, avg, max, min, calculated_pf)")

    model_config = ConfigDict(use_enum_values=True)


class SourceConfig(BaseModel):
    """Source devices configuration"""

    model: str = Field(..., description="Source device model (e.g., 'ADTEK_CPM10')")
    slave_ids: list[int] | None = Field(
        default=None, description="Optional: specific slave IDs to aggregate. None or [] = all devices of this model"
    )

    @field_validator("slave_ids")
    def validate_slave_ids(cls, v):
        """Validate that slave_ids contains positive integers if specified"""
        if v is not None and len(v) > 0:
            for slave_id in v:
                if slave_id <= 0:
                    raise ValueError(f"slave_id must be positive integer, got {slave_id}")
        return v


class TargetConfig(BaseModel):
    """Target virtual device configuration"""

    model: str = Field(..., description="Target device model (same as source for compatibility)")
    slave_id: str | int = Field(
        ..., description="Target slave ID. Use 'auto' for max(all_devices) + 1, or specify explicit integer"
    )

    @field_validator("slave_id")
    def validate_slave_id(cls, v):
        """Validate slave_id is either 'auto' or positive integer"""
        if isinstance(v, str):
            if v != "auto":
                raise ValueError(f"slave_id string must be 'auto', got '{v}'")
        elif isinstance(v, int):
            if v <= 0:
                raise ValueError(f"slave_id must be positive integer, got {v}")
        return v


class AggregationConfig(BaseModel):
    """Aggregation behavior configuration"""

    error_handling: ErrorHandling = Field(
        default=ErrorHandling.FAIL_FAST, description="How to handle read failures from source devices"
    )
    fields: list[AggregatedFieldConfig] = Field(..., description="List of fields to aggregate")

    @field_validator("fields")
    def validate_fields_not_empty(cls, v):
        """Validate that at least one field is specified"""
        if len(v) == 0:
            raise ValueError("aggregation.fields cannot be empty, must specify at least one field to aggregate")
        return v

    model_config = ConfigDict(use_enum_values=True)


class VirtualDeviceConfig(BaseModel):
    """Configuration for a single virtual device"""

    id: str = Field(..., description="Unique identifier for this virtual device")
    enabled: bool = Field(default=True, description="Whether this virtual device is enabled")
    description: str | None = Field(default=None, description="Human-readable description")
    type: Literal["aggregated_power_meter"] = Field(..., description="Virtual device type (currently only power meter)")
    source: SourceConfig = Field(..., description="Source devices configuration")
    target: TargetConfig = Field(..., description="Target virtual device configuration")
    aggregation: AggregationConfig = Field(..., description="Aggregation behavior configuration")


class VirtualDevicesConfigSchema(BaseModel):
    """Root configuration schema for virtual devices"""

    version: str = Field(default="1.0.0", description="Configuration version")
    virtual_devices: list[VirtualDeviceConfig] = Field(default_factory=list, description="List of virtual devices")

    @field_validator("virtual_devices")
    def validate_unique_ids(cls, v):
        """Validate that all virtual device IDs are unique"""
        ids = [vdev.id for vdev in v]
        if len(ids) != len(set(ids)):
            duplicates = [id for id in ids if ids.count(id) > 1]
            raise ValueError(f"Duplicate virtual device IDs found: {set(duplicates)}")
        return v
