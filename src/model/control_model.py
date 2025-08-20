from enum import StrEnum

from pydantic import BaseModel, model_validator

from model.enum.condition_enum import ConditionOperator, ConditionType


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
    def check_value_type(self) -> "ControlActionModel":
        if self.type == ControlActionType.SET_FREQUENCY:
            if not isinstance(self.value, (int, float)):
                raise ValueError(f"{ControlActionType.SET_FREQUENCY} requires a numeric value")
            self.value = float(self.value)

        if self.type in {ControlActionType.WRITE_DO, ControlActionType.RESET}:
            if not isinstance(self.value, int):
                raise ValueError(f"{self.type} requires an int value")

        return self


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
    def check_required_fields(self) -> "ControlConditionModel":
        if self.type == ConditionType.THRESHOLD:
            if not isinstance(self.source, str) or not self.source:
                raise ValueError("Threshold condition must include a single 'source'")
        if self.type == ConditionType.DIFFERENCE:
            if not isinstance(self.source, list) or len(self.source) != 2:
                raise ValueError("Difference condition must include exactly 2 sources")
        return self
