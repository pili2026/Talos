from datetime import datetime

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


class AlertConditionModel(BaseModel):
    """
    Alert Condition Model

    Supports both single-source and multi-source (aggregate) alerts.

    Examples:
        Single source (threshold):
            sources: ["O2_PCT"]
            type: "threshold"
            condition: "lt"
            threshold: 1.5

        Multi-source (average):
            sources: ["AIn02", "AIn03"]
            type: "average"
            condition: "gt"
            threshold: 40.0
    """

    name: str
    code: str
    sources: list[str]  # Unified: always use list, even for single source
    condition: ConditionOperator
    threshold: float
    severity: AlertSeverity = AlertSeverity.INFO
    type: ConditionType = ConditionType.THRESHOLD
    message: str | None = None  # Optional custom message template

    @field_validator("sources")
    @classmethod
    def validate_sources_not_empty(cls, v):
        """Ensure sources list is not empty"""
        if not v or len(v) == 0:
            raise ValueError("sources must have at least one element")
        return v

    @model_validator(mode="after")
    def validate_aggregate_sources(self):
        """For aggregate types, require at least 2 sources"""
        if self.type in {
            ConditionType.AVERAGE,
            ConditionType.SUM,
            ConditionType.MIN,
            ConditionType.MAX,
        }:
            if len(self.sources) < 2:
                raise ValueError(f"{self.type.value} requires at least 2 sources, got {len(self.sources)}")
        return self


class InstanceConfig(BaseModel):
    display_name: str | None = None
    use_default_alerts: bool = False
    alerts: list[AlertConditionModel] | None = None


class ModelConfig(BaseModel):
    default_alerts: list[AlertConditionModel] = Field(default_factory=list)
    instances: dict[str, InstanceConfig] = Field(default_factory=dict)
