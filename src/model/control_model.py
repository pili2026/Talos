from enum import StrEnum

from pydantic import BaseModel, model_validator

from model.condition_enum import ConditionOperator, ConditionType


# TODO: Uppercase the enum values to match the convention
class ControlActionType(StrEnum):
    SET_FREQUENCY = "set_frequency"
    WRITE_DO = "write_do"
    RESET = "reset"
    TURN_OFF = "turn_off"
    TURN_ON = "turn_on"


class ControlActionModel(BaseModel):
    model: str | None = None
    slave_id: int | None = None
    type: ControlActionType
    target: str | None = None
    value: float | int | None = None
    source: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def check_value_type(cls, model: "ControlActionModel") -> "ControlActionModel":
        if model.type == ControlActionType.SET_FREQUENCY:
            if not isinstance(model.value, (int, float)):
                raise ValueError(f"{ControlActionType.SET_FREQUENCY} requires a numeric value")
            model.value = float(model.value)

        if model.type in {ControlActionType.WRITE_DO, ControlActionType.RESET}:
            if not isinstance(model.value, int):
                raise ValueError(f"{model.type} requires an int value")

        return model


class ControlConditionModel(BaseModel):
    name: str
    code: str
    type: ConditionType
    operator: ConditionOperator
    threshold: float
    source: str | list[str] | None = None
    action: ControlActionModel
    priority: int = 0

    @model_validator(mode="after")
    def check_required_fields(cls, model: "ControlConditionModel") -> "ControlConditionModel":
        if model.type == ConditionType.THRESHOLD:
            if not model.source or not isinstance(model.source, str):
                raise ValueError("Threshold condition must include a single 'source'")
        if model.type == ConditionType.DIFFERENCE:
            if not isinstance(model.source, list) or len(model.source) != 2:
                raise ValueError("Difference condition must include exactly 2 sources")
        return model
