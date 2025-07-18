from dataclasses import dataclass
from datetime import datetime


@dataclass
class AlertMessage:
    device_key: str
    level: str  # "INFO", "WARNING", "ERROR"
    message: str
    alert_code: str
    timestamp: datetime
