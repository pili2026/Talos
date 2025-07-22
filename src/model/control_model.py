from pydantic import BaseModel, model_validator

from model.condition_enum import ConditionOperator, ConditionType


class ControlActionModel(BaseModel):
    device_id: str
    type: str
    target: str | None = "frequency"
    value: float | int

    @model_validator(mode="after")
    def check_value_type(cls, model: "ControlActionModel") -> "ControlActionModel":
        if model.type == "set_frequency" and not isinstance(model.value, float):
            raise ValueError(f"[{model.device_id}] set_frequency requires a float value")
        elif model.type == "write_do" and not isinstance(model.value, int):
            raise ValueError(f"[{model.device_id}] write_do requires an int value")
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
