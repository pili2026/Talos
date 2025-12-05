from enum import StrEnum


class RegisterType(StrEnum):
    HOLDING = "holding"
    INPUT = "input"
    DISCRETE_INPUT = "discrete_input"
    COIL = "coil"
