from enum import Enum


class AlertState(str, Enum):
    """
    Alert lifecycle states:
    NORMAL: No violation detected
    TRIGGERED: First violation detected, notification sent
    ACTIVE: Continuous violation, no notification
    RESOLVED: Condition recovered, recovery notification sent
    """

    NORMAL = "NORMAL"
    TRIGGERED = "TRIGGERED"
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"
