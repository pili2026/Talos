from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from model.control_composite import CompositeNode
from model.enum.condition_enum import ControlActionType
from model.policy_model import PolicyConfig

logger = logging.getLogger(__name__)


class ControlActionModel(BaseModel):
    """
    Control Action Configuration Model

    Notes:
    - `slave_id` is always represented as `str` (normalized across producers/consumers).
    - Type-specific value validation:
      * SET_FREQUENCY/ADJUST_FREQUENCY require numeric values (converted to float)
      * WRITE_DO/RESET require integer values
      * TURN_ON/TURN_OFF do not require values
    - Input normalization: strip whitespace for string fields; convert int `slave_id` to str.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,  # automatically strip leading/trailing whitespace for strings
        use_enum_values=False,  # keep Enum names on serialization (easier for debugging)
        validate_assignment=True,  # allow validation on assignment
    )

    model: str | None = None
    slave_id: str | None = None
    type: ControlActionType | None = None  # Optional for soft validation
    target: str | None = None
    value: float | int | None = None
    source: str | None = None
    reason: str | None = None

    # ---- Normalization (strings & types) ----
    @field_validator("model", "slave_id", "target", mode="before")
    @classmethod
    def coerce_to_str(cls, v):
        """Convert various input types to string and normalize"""
        if v is None:
            return None
        try:
            return str(v).strip()
        except (TypeError, AttributeError) as e:
            logger.warning(f"[ACTION] Failed to convert field to string: {v} - {e}")
            return str(v) if v is not None else None

    # ---- Validation rules (by action type) ----
    @model_validator(mode="after")
    def validate_by_action_type(self) -> ControlActionModel:
        """Validate action configuration based on action type"""
        # Skip validation if type is None (will be filtered out at runtime)
        if self.type is None:
            return self

        try:
            # SET_FREQUENCY and ADJUST_FREQUENCY require numeric; coerce to float
            if self.type in {ControlActionType.SET_FREQUENCY, ControlActionType.ADJUST_FREQUENCY}:
                try:
                    new_value = float(self.value) if self.value is not None else 0.0
                except (ValueError, TypeError) as e:
                    logger.warning(
                        f"[ACTION] {self.type.value} requires numeric value, "
                        f"got {self.value!r} ({type(self.value).__name__}). Fallback to 0.0. Error: {e}"
                    )
                    new_value = 0.0
                object.__setattr__(self, "value", new_value)
                return self

            # WRITE_DO / RESET require an integer
            elif self.type in {ControlActionType.WRITE_DO, ControlActionType.RESET}:
                try:
                    new_value = int(self.value) if self.value is not None else 0
                except (ValueError, TypeError) as e:
                    logger.warning(
                        f"[ACTION] {self.type.value} requires integer value, "
                        f"got {self.value!r} ({type(self.value).__name__}). Fallback to 0. Error: {e}"
                    )
                    new_value = 0
                object.__setattr__(self, "value", new_value)
                return self

            # TURN_ON / TURN_OFF do not require value (ignore if provided)
            elif self.type in {ControlActionType.TURN_ON, ControlActionType.TURN_OFF}:
                if self.value is not None:
                    logger.info(f"[ACTION] {self.type.value} ignores value={self.value!r}; set to None")
                    object.__setattr__(self, "value", None)
                return self

        except Exception as e:
            logger.error(f"[ACTION] Unexpected error during action validation: {e}")

        return self


# --- Control Condition Model ---
class ControlConditionModel(BaseModel):
    """
    Control Condition Configuration Model

    Represents a complete control rule including:
    - Identification (name, code, priority)
    - Trigger conditions (composite)
    - Control policy (policy)
    - Action to execute (action)

    Validation approach: Allow parsing with missing/invalid components,
    filter out invalid rules at runtime in get_control_list().
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        use_enum_values=False,
        validate_assignment=True,
        populate_by_name=True,
    )

    name: str
    code: str
    action: ControlActionModel | None = None  # Optional for soft validation
    priority: int = 0
    composite: CompositeNode | None = Field(default=None)
    policy: PolicyConfig | None = Field(default=None)
