from enum import StrEnum


class ControlActionType(StrEnum):
    SET_FREQUENCY = "set_frequency"
    ADJUST_FREQUENCY = "adjust_frequency"
    WRITE_DO = "write_do"
    RESET = "reset"
    TURN_OFF = "turn_off"
    TURN_ON = "turn_on"


class ConditionType(StrEnum):
    THRESHOLD = "threshold"
    DIFFERENCE = "difference"
    SINGLE = "single"


class ConditionOperator(StrEnum):
    GREATER_THAN = "gt"
    LESS_THAN = "lt"
    EQUAL = "eq"
    BETWEEN = "between"


class ControlCompositeType(StrEnum):
    ALL = "all"
    ANY = "any"
    NOT = "not_"


class ControlPolicyType(StrEnum):
    DISCRETE_SETPOINT = "discrete_setpoint"
    ABSOLUTE_LINEAR = "absolute_linear"
    INCREMENTAL_LINEAR = "incremental_linear"
