from __future__ import annotations

import logging
from datetime import time

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.model.control_composite import CompositeNode
from core.model.enum.condition_enum import ControlActionType, ControlPolicyType
from core.schema.policy_schema import PolicyConfig

logger = logging.getLogger(__name__)


class TimeRange(BaseModel):
    """
    Time range definition

    Used to specify the effective period of a control condition.
    Supports ranges that cross midnight (e.g., 22:00 - 06:00).
    """

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    start: str = Field(..., description="Start time in HH:MM format (24-hour)", examples=["09:00", "22:00", "00:00"])
    end: str = Field(..., description="End time in HH:MM format (24-hour)", examples=["17:00", "06:00", "23:59"])

    @field_validator("start", "end")
    @classmethod
    def validate_time_format(cls, v: str, info) -> str:
        """
        Validate that the time format is HH:MM

        Args:
            v: Time string to validate
            info: Field information

        Returns:
            Validated time string

        Raises:
            ValueError: If the format is invalid
        """
        if not v:
            raise ValueError(f"{info.field_name} cannot be empty")

        try:
            # Attempt to parse the value as a time object
            time.fromisoformat(v)
            return v
        except ValueError as e:
            raise ValueError(
                f"Invalid time format for {info.field_name}: '{v}'. " f"Expected HH:MM (24-hour format). Error: {e}"
            ) from e

    @model_validator(mode="after")
    def validate_time_range(self) -> TimeRange:
        """
        Validate the logical correctness of the time range

        Note:
        - start > end is allowed (cross-midnight cases, e.g., 22:00 - 06:00)
        - start == end is not allowed
        """
        if self.start == self.end:
            raise ValueError(
                f"start and end cannot be the same: {self.start}. " f"Use different times to define a valid range"
            )

        return self

    def __str__(self) -> str:
        """Human-readable representation"""
        return f"{self.start}-{self.end}"


class ControlActionSchema(BaseModel):
    """
    Control Action Configuration Model

    Notes:
    - `slave_id` is always represented as `str` (normalized across producers/consumers).
    - Type-specific value validation:
      * SET_FREQUENCY/ADJUST_FREQUENCY require numeric values (converted to float)
      * WRITE_DO/RESET require integer values
      * TURN_ON/TURN_OFF do not require values
    - Input normalization: strip whitespace for string fields; convert int `slave_id` to str.
    - `priority` is populated by Evaluator during runtime (optional in config)
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
    # Tracking metadata (for logging/debugging)
    action_origin: str | None = None  # Origin of this action (e.g., "local_rule", "mqtt_command")
    reason: str | None = None
    emergency_override: bool = Field(default=False)
    priority: int | None = None  # Populated by Evaluator at runtime

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
    def validate_by_action_type(self) -> ControlActionSchema:
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
class ConditionSchema(BaseModel):
    """
    Control Condition Configuration Model

    Represents a complete control rule including:
    - Identification (name, code, priority)
    - Trigger conditions (composite)
    - Control policy (policy)
    - Actions to execute (actions) - supports multiple devices
    - Blocking flag (blocking) - stops evaluation of lower priority rules

    Execution Logic:
    - Rules are evaluated in priority order (lower number = higher priority)
    - All triggered rules are executed (cumulative mode)
    - If a rule has blocking=True, subsequent rules are skipped
    - Each rule can define multiple actions for different devices
    - Higher priority actions (lower number) protect their writes from being overwritten

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
    actions: list[ControlActionSchema] = Field(
        min_length=1, default_factory=list, description="List of actions to execute when condition is met"
    )
    priority: int = 0
    blocking: bool = Field(default=False, description="If True, prevents evaluation of lower priority rules")
    composite: CompositeNode | None = Field(default=None)
    policy: PolicyConfig | None = Field(default=None)

    active_time_ranges: list[TimeRange] | None = Field(
        default=None,
        description=(
            "Time ranges when this condition is active. "
            "If not specified, condition is active at all times. "
            "Multiple ranges are OR-ed (active if within ANY range)"
        ),
        examples=[
            [{"start": "09:00", "end": "12:00"}],
            [{"start": "08:00", "end": "12:00"}, {"start": "13:00", "end": "17:00"}],
            [{"start": "22:00", "end": "06:00"}],  # Overnight
        ],
    )

    @model_validator(mode="after")
    def validate_actions_not_empty(self) -> ConditionSchema:
        """Validate that at least one action is defined (soft validation)"""
        if not self.actions:
            logger.warning(f"[SCHEMA] Rule '{self.code}': no actions defined (will be filtered at runtime)")
        return self

    @model_validator(mode="after")
    def validate_actions_required(self) -> ConditionSchema:
        if "actions" not in self.model_fields_set:
            raise ValueError("actions field is required")
        if not self.actions:
            raise ValueError("actions cannot be empty")
        return self

    @model_validator(mode="after")
    def validate_policy_input_source(self):
        """Validate that linear policies reference valid conditions"""
        if not self.policy or not self.composite:
            return self

        # Linear policies require input_source
        if self.policy.type in {ControlPolicyType.ABSOLUTE_LINEAR, ControlPolicyType.INCREMENTAL_LINEAR}:
            if not self.policy.input_source:
                raise ValueError(
                    f"Control '{self.code}': {self.policy.type.value} policy " f"requires 'input_source' field"
                )

            # Verify input_source references a valid condition
            if not self._find_condition_by_id(self.composite, self.policy.input_source):
                raise ValueError(
                    f"Control '{self.code}': Policy input_source='{self.policy.input_source}' "
                    f"not found in composite. Please add sources_id='{self.policy.input_source}' "
                    f"to the condition you want to reference."
                )

        return self

    def _find_condition_by_id(self, node: CompositeNode, sources_id: str) -> CompositeNode | None:
        """Recursively find condition by sources_id"""
        if node.sources_id == sources_id:
            return node

        for child_list in [node.all, node.any]:
            if child_list:
                for child in child_list:
                    result = self._find_condition_by_id(child, sources_id)
                    if result:
                        return result

        if node.not_:
            return self._find_condition_by_id(node.not_, sources_id)

        return None
