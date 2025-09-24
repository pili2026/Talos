import logging

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from model.enum.condition_enum import ConditionType, ControlPolicyType

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
    condition_type: ConditionType = ConditionType.SINGLE
    source: str | None = None  # Used for "single" condition type
    sources: list[str] | None = None  # Used for "difference" condition type (>=2 required)
    abs: bool = False  # Whether to take absolute value in difference mode

    # Deadband and frequency limits (applicable to both linear types)
    deadband: float = 0.0
    min_freq: float | None = None
    max_freq: float | None = None

    # Absolute linear policy specific fields
    base_freq: float | None = None
    gain_hz_per_unit: float | None = None

    # Incremental linear policy specific fields
    max_step_hz: float | None = None

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
            try:
                if self.condition_type == ConditionType.SINGLE:
                    if not self.source:
                        problems.append("policy.source required when condition_type='single'")
                else:  # ConditionType.DIFFERENCE
                    if not self.sources or len(self.sources) < 2:
                        problems.append("policy.sources (>=2 items) required when condition_type='difference'")
            except AttributeError as e:
                problems.append(f"error validating input sources: {e}")

        # Policy-specific requirement validation
        try:
            if self.type == ControlPolicyType.ABSOLUTE_LINEAR:
                missing_fields = []
                if self.base_freq is None:
                    missing_fields.append("base_freq")
                if self.gain_hz_per_unit is None:
                    missing_fields.append("gain_hz_per_unit")

                if missing_fields:
                    problems.append(f"absolute_linear policy requires: {', '.join(missing_fields)}")

            elif self.type == ControlPolicyType.INCREMENTAL_LINEAR:
                if self.gain_hz_per_unit is None:
                    problems.append("incremental_linear policy requires gain_hz_per_unit")
                if self.max_step_hz is not None and self.max_step_hz <= 0:
                    problems.append("max_step_hz must be positive when specified")

        except AttributeError as e:
            problems.append(f"error validating policy-specific requirements: {e}")

        # Frequency limit validation
        try:
            if self.min_freq is not None and self.max_freq is not None:
                if self.min_freq > self.max_freq:
                    problems.append("min_freq must be <= max_freq")
        except (TypeError, AttributeError) as e:
            problems.append(f"error validating frequency limits: {e}")

        # Handle validation problems with soft validation approach
        if problems:
            logger.warning(f"[POLICY] Invalid policy configuration: {problems}")
            object.__setattr__(self, "invalid", True)

        return self
