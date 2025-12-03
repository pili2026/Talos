from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from model.enum.alert_enum import AlertSeverity
from model.enum.condition_enum import ConditionOperator, ConditionType


class AlertMessageModel(BaseModel):
    model: str
    slave_id: int
    level: AlertSeverity
    message: str
    alert_code: str
    timestamp: datetime


# ============================================================
# Base Alert Configuration
# ============================================================


class BaseAlertConfig(BaseModel):
    """Base configuration for all alert types"""

    name: str
    code: str
    sources: list[str]
    severity: AlertSeverity = AlertSeverity.INFO
    message: str | None = None

    @field_validator("sources")
    @classmethod
    def validate_sources_not_empty(cls, v):
        """Ensure sources list is not empty"""
        if not v or len(v) == 0:
            raise ValueError("sources must have at least one element")
        return v


# ============================================================
# Threshold Alert (Single Source)
# ============================================================


class ThresholdAlertConfig(BaseAlertConfig):
    """
    Single source threshold alert.
    Example:
        sources: ["O2_PCT"]
        type: "threshold"
        condition: "lt"
        threshold: 1.5
    """

    type: ConditionType = ConditionType.THRESHOLD
    condition: ConditionOperator
    threshold: float

    @model_validator(mode="after")
    def validate_single_source(self):
        """Threshold alerts should typically use single source"""
        # Note: We don't enforce single source strictly, as threshold can work with multiple
        # sources if needed (though aggregate types are more appropriate for that)
        return self


# ============================================================
# Aggregate Alerts (Multiple Sources)
# ============================================================


class AggregateAlertConfig(BaseAlertConfig):
    """
    Multi-source aggregate alert (average, sum, min, max).
    Example:
        sources: ["AIn02", "AIn03"]
        type: "average"
        condition: "gt"
        threshold: 40.0
    """

    type: Literal[ConditionType.AVERAGE, ConditionType.SUM, ConditionType.MIN, ConditionType.MAX]
    condition: ConditionOperator
    threshold: float

    @model_validator(mode="after")
    def validate_multiple_sources(self):
        """Aggregate types require at least 2 sources"""
        if len(self.sources) < 2:
            raise ValueError(f"{self.type.value} requires at least 2 sources, got {len(self.sources)}")
        return self


# ============================================================
# Schedule Expected State Alert (Time-based)
# ============================================================


class ScheduleExpectedStateAlertConfig(BaseAlertConfig):
    """
    Time-based expected state alert.
    Checks if device state matches expected state during shutdown periods
    (outside work_hours defined in time_condition).

    Example:
        sources: ["RW_ON_OFF"]
        type: "schedule_expected_state"
        expected_state: 0  # or "off"
        use_work_hours: true
    """

    type: ConditionType = ConditionType.SCHEDULE_EXPECTED_STATE
    expected_state: int | str  # 0/"off" or 1/"on"
    use_work_hours: bool = True  # Whether to use time_condition work_hours

    @field_validator("expected_state")
    @classmethod
    def normalize_expected_state(cls, v):
        """Normalize string values to int"""
        if isinstance(v, str):
            state_map = {"off": 0, "on": 1}
            normalized = state_map.get(v.lower())
            if normalized is None:
                raise ValueError(f"expected_state must be 0/1 or 'on'/'off', got '{v}'")
            return normalized
        if v not in (0, 1):
            raise ValueError(f"expected_state must be 0 or 1, got {v}")
        return v

    @model_validator(mode="after")
    def validate_single_source(self):
        """Schedule expected state alerts require exactly 1 source (device state parameter)"""
        if len(self.sources) != 1:
            raise ValueError(
                f"schedule_expected_state requires exactly 1 source (device state parameter), "
                f"got {len(self.sources)}"
            )
        return self


# ============================================================
# Union Type for All Alert Configurations
# ============================================================

AlertConditionModel = ThresholdAlertConfig | AggregateAlertConfig | ScheduleExpectedStateAlertConfig


# ============================================================
# Instance and Model Configuration (unchanged)
# ============================================================


class InstanceConfig(BaseModel):
    display_name: str | None = None
    use_default_alerts: bool = False
    alerts: list[AlertConditionModel] | None = None


class ModelConfig(BaseModel):
    default_alerts: list[AlertConditionModel] = Field(default_factory=list)
    instances: dict[str, InstanceConfig] = Field(default_factory=dict)
