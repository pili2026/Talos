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
    AVERAGE = "average"
    SUM = "sum"
    MIN = "min"
    MAX = "max"
    SCHEDULE_EXPECTED_STATE = "schedule_expected_state"


class ConditionOperator(StrEnum):
    GREATER_THAN = "gt"
    GREATER_THAN_OR_EQUAL = "gte"
    LESS_THAN = "lt"
    LESS_THAN_OR_EQUAL = "lte"
    EQUAL = "eq"
    BETWEEN = "between"
    NOT_EQUAL = "neq"


class ControlCompositeType(StrEnum):
    ALL = "all"
    ANY = "any"
    NOT = "not_"


class ControlPolicyType(StrEnum):
    DISCRETE_SETPOINT = "discrete_setpoint"
    ABSOLUTE_LINEAR = "absolute_linear"
    INCREMENTAL_LINEAR = "incremental_linear"
