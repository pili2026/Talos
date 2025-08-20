from datetime import datetime

from pydantic import BaseModel, Field

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
    name: str
    code: str
    source: str
    condition: ConditionOperator
    threshold: float
    severity: AlertSeverity = AlertSeverity.INFO
    type: str = ConditionType.THRESHOLD


class InstanceConfig(BaseModel):
    display_name: str | None = None
    use_default_alerts: bool = False
    alerts: list[AlertConditionModel] | None = None


class ModelConfig(BaseModel):
    default_alerts: list[AlertConditionModel] = Field(default_factory=list)
    instances: dict[str, InstanceConfig] = Field(default_factory=dict)
