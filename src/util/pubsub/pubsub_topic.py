from enum import StrEnum


class PubSubTopic(StrEnum):
    ALERT_WARNING = "ALERT_EARNING"
    DEVICE_SNAPSHOT = "DEVICE_SNAPSHOT"
    CONTROL = "CONTROL"
