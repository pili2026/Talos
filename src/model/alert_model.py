from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from model.condition_enum import ConditionOperator


class AlertSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class AlertMessageModel(BaseModel):
    device_key: str
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
    type: str = "threshold"
