from enum import StrEnum


class ControlActionType(StrEnum):
    SET_FREQUENCY = "set_frequency"
    WRITE_DO = "write_do"
    RESET = "reset"
    TURN_OFF = "turn_off"
    TURN_ON = "turn_on"


class ConditionType(StrEnum):
    THRESHOLD = "threshold"
    DIFFERENCE = "difference"


class ConditionOperator(StrEnum):
    GREATER_THAN = "gt"
    LESS_THAN = "lt"
    EQUAL = "eq"
    BETWEEN = "between"


class ControlCompositeType(StrEnum):
    ALL = "all"
    ANY = "any"
    NOT = "not_"
