from enum import StrEnum

from pydantic import BaseModel, model_validator

from model.condition_enum import ConditionOperator, ConditionType


class ControlActionType(StrEnum):
    SET_FREQUENCY = "set_frequency"
    WRITE_DO = "write_do"
    RESET = "reset"


class ControlActionModel(BaseModel):
    device_id: str
    type: ControlActionType
    target: str | None
    value: float | int

    @model_validator(mode="after")
    def check_value_type(cls, model: "ControlActionModel") -> "ControlActionModel":
        if model.type == ControlActionType.SET_FREQUENCY and not isinstance(model.value, float):
            raise ValueError(f"[{model.device_id}] set_frequency requires a float value")
        if model.type == ControlActionType.WRITE_DO and not isinstance(model.value, int):
            raise ValueError(f"[{model.device_id}] write_do requires an int value")
        if model.type == ControlActionType.RESET and not isinstance(model.value, int):
            raise ValueError(f"[{model.device_id}] reset requires an int value")
        return model


class ControlConditionModel(BaseModel):
    name: str
    code: str
    condition_type: ConditionType
    operator: ConditionOperator
    threshold: float
    source: str | list[str] | None = None
    action: ControlActionModel

    @model_validator(mode="after")
    def check_required_fields(cls, model: "ControlConditionModel") -> "ControlConditionModel":
        if model.condition_type == ConditionType.THRESHOLD:
            if not model.source:
                raise ValueError("Threshold condition must include 'pin'")
        elif model.condition_type == ConditionType.DIFFERENCE:
            if not model.source or len(model.source) != 2:
                raise ValueError("Difference condition must include exactly 2 pins")
        return model
