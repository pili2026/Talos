from enum import StrEnum


class NotificationMode(StrEnum):
    """Notification delivery mode"""

    BROADCAST = "broadcast"
    FALLBACK = "fallback"
    SINGLE = "single"
