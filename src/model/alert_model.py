from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from model.condition_enum import ConditionOperator, ConditionType


class AlertSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


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
