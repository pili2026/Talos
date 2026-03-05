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
    SCHEDULE_THRESHOLD = "schedule_threshold"
    TIME_ELAPSED = "time_elapsed"


class AggregationType(StrEnum):
    """
    Aggregation methods for combining multiple pin values within a single Source.

    Used in Source.aggregation to specify how multiple pins from the same device
    should be combined into a single value before cross-source operations.

    Examples:
        - AVERAGE: (pin1 + pin2 + pin3) / 3
        - SUM: pin1 + pin2 + pin3
        - MIN: min(pin1, pin2, pin3)
        - MAX: max(pin1, pin2, pin3)
        - FIRST: pin1 (use first value in list)
        - LAST: pin3 (use last value in list)

    Note: This is separate from ConditionType to maintain semantic clarity:
        - ConditionType: How to evaluate across multiple Sources
        - AggregationType: How to aggregate within a single Source
    """

    AVERAGE = "average"
    SUM = "sum"
    MIN = "min"
    MAX = "max"
    FIRST = "first"
    LAST = "last"


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


class SwitchMode(StrEnum):
    NORMAL = "normal"
    PULSE = "pulse"
