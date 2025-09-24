from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from model.control_composite import CompositeNode
from model.enum.condition_enum import ControlActionType
from model.policy_model import PolicyConfig

logger = logging.getLogger(__name__)


class ControlActionModel(BaseModel):
    """
    Notes:
    - `slave_id` is always represented as `str` (normalized across producers/consumers).
    - Minimal required type checks for `value` by action type:
    * SET_FREQUENCY requires a numeric (float).
    * WRITE_DO / RESET require an integer (int).
    * TURN_ON / TURN_OFF do not require `value`.
    - Input normalization: strip whitespace for model/slave_id/target; convert int `slave_id` to str.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,  # automatically strip leading/trailing whitespace for strings
        use_enum_values=False,  # keep Enum names on serialization (easier for debugging)
        validate_assignment=True,  # allow validation on assignment
    )

    model: str | None = None
    slave_id: str | None = None
    type: ControlActionType | None = None
    target: str | None = None
    value: float | int | None = None
    source: str | None = None
    reason: str | None = None

    # ---- Normalization (strings & types) ----
    @field_validator("model", "slave_id", "target", mode="before")
    @classmethod
    def coerce_to_str(cls, v):
        return None if v is None else str(v).strip()  # Allow non-string inputs (e.g., int/bool) and normalize to str

    # ---- Validation rules (by action type) ----
    @model_validator(mode="after")
    def validate_by_action_type(self) -> ControlActionModel:
        # Skip validation if type is None (will be filtered out at runtime)
        if self.type is None:
            return self

        # SET_FREQUENCY and ADJUST_FREQUENCY require numeric; coerce to float
        if self.type in {ControlActionType.SET_FREQUENCY, ControlActionType.ADJUST_FREQUENCY}:
            try:
                new_value = float(self.value)
            except Exception:
                logger.warning(f"[CONFIG] {self.type} requires numeric value, got {self.value!r}. Fallback to 0.0")
                new_value = 0.0
            object.__setattr__(self, "value", new_value)
            return self

        # WRITE_DO / RESET require an integer
        if self.type in {ControlActionType.WRITE_DO, ControlActionType.RESET}:
            try:
                new_value = int(self.value)
            except Exception:
                logger.warning(f"[CONFIG] {self.type} requires int value, got {self.value!r}. Fallback to 0")
                new_value = 0
            object.__setattr__(self, "value", new_value)
            return self

        # TURN_ON / TURN_OFF do not require value (ignore if provided)
        if self.type in {ControlActionType.TURN_ON, ControlActionType.TURN_OFF}:
            if self.value is not None:
                logger.info(f"[CONFIG] {self.type} ignores value={self.value!r}; set to None")
                object.__setattr__(self, "value", None)
            return self

        return self


# --- Conditions ---
class ControlConditionModel(BaseModel):
    """
    Specification highlights:
    - type == THRESHOLD: `source` must be a single field (str)
    - type == DIFFERENCE: `source` must be two fields (list[str] with len == 2)
    - operator supports GREATER_THAN / LESS_THAN / EQUAL (EQUAL is strict equality for now)
    - `threshold` is float
    - `priority` is int (larger = higher; for same priority, earlier definition wins)
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        use_enum_values=False,
        validate_assignment=True,
        populate_by_name=True,
    )

    name: str
    code: str
    action: ControlActionModel | None = None
    priority: int = 0
    composite: CompositeNode | None = Field(default=None)
    policy: PolicyConfig | None = Field(default=None)
