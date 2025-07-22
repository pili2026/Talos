from enum import StrEnum


class ConditionType(StrEnum):
    THRESHOLD = "threshold"
    DIFFERENCE = "difference"


class ConditionOperator(StrEnum):
    GREATER_THAN = "gt"
    LESS_THAN = "lt"
    EQUAL = "eq"
