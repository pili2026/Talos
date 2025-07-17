from dataclasses import dataclass
from datetime import datetime


@dataclass
class AlertMessage:
    device_id: str
    level: str  # "INFO", "WARNING", "ERROR"
    message: str
    timestamp: datetime
