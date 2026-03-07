from enum import StrEnum


class PendingActionKind(StrEnum):
    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"
    CUSTOM = "custom"
