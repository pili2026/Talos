import logging

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.model.enum.condition_enum import ConditionType, ControlPolicyType

logger = logging.getLogger(__name__)


class PolicyConfig(BaseModel):
    """
    Control Policy Configuration

    Policy Types:
    - discrete_setpoint: Sets fixed value when condition is met (backward compatible,
                        Evaluator can directly use action.value)
    - absolute_linear: Maps input linearly to absolute frequency value;
                      Evaluator computes and overwrites action.value
    - incremental_linear: Computes frequency delta from input;
                         Executor must implement adjust_frequency action

    Validation Principle:
    Never raise exceptions; instead, log warnings and mark invalid=True,
    leaving filtering to the parent level for graceful degradation.
    """

    model_config = ConfigDict(
        extra="forbid",  # Reject unknown fields like legacy 'source_kind'
        str_strip_whitespace=True,  # Auto-trim string fields
        use_enum_values=False,  # Keep enum names for better debugging
        validate_assignment=True,  # Validate on field assignment
    )

    # Core policy configuration
    type: ControlPolicyType

    # Input source configuration
    condition_type: ConditionType = ConditionType.THRESHOLD
    sources: list[str] | None = None  # Used for "difference" condition type (>=2 required)
    abs: bool = False  # Whether to take absolute value in difference mode

    # Absolute linear policy specific fields
    base_freq: float | None = None
    base_temp: float | None = None
    gain_hz_per_unit: float | None = None

    # Soft validation state flag
    invalid: bool = Field(default=False)

    @field_validator("sources")
    @classmethod
    def validate_and_normalize_sources(cls, v):
        """Normalize sources list by trimming strings and removing empty values"""
        if v is None:
            return None
        try:
            normalized = [str(s).strip() for s in v if str(s).strip()]
            return normalized or None
        except (TypeError, AttributeError) as e:
            logger.warning(f"[POLICY] Failed to normalize sources {v}: {e}")
            return None

    @model_validator(mode="after")
    def validate_semantic_requirements(self):
        """
        Validate semantic requirements for different policy types.
        Uses soft validation: logs warnings instead of raising exceptions.
        """
        problems: list[str] = []

        # Input source validation (discrete_setpoint doesn't need sources)
        if self.type != ControlPolicyType.DISCRETE_SETPOINT:
            if self.condition_type == ConditionType.THRESHOLD:
                if not self.sources or len(self.sources) != 1:
                    problems.append("policy.sources must contain exactly 1 item when condition_type='threshold'")
            else:  # ConditionType.DIFFERENCE
                if not self.sources or len(self.sources) != 2:
                    problems.append("policy.sources must contain exactly 2 items when condition_type='difference'")

        # Policy-specific requirement validation
        if self.type == ControlPolicyType.ABSOLUTE_LINEAR:
            missing_fields = []
            if self.base_freq is None:
                missing_fields.append("base_freq")
            if self.base_temp is None:
                missing_fields.append("base_temp")
            if self.gain_hz_per_unit is None:
                missing_fields.append("gain_hz_per_unit")

            if missing_fields:
                problems.append(f"absolute_linear policy requires: {', '.join(missing_fields)}")

        elif self.type == ControlPolicyType.INCREMENTAL_LINEAR:
            if self.gain_hz_per_unit is None:
                problems.append("incremental_linear policy requires gain_hz_per_unit")

        # Handle validation problems with soft validation approach
        if problems:
            logger.warning(f"[POLICY] Invalid policy configuration: {problems}")
            object.__setattr__(self, "invalid", True)

        return self
