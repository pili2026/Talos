from enum import StrEnum


class PubSubTopic(StrEnum):
    ALERT_WARNING = "alert_warning"
    DEVICE_SNAPSHOT = "DEVICE_SNAPSHOT"
