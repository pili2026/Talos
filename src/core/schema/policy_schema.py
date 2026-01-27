import logging

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.model.enum.condition_enum import ControlPolicyType

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

    type: ControlPolicyType = Field(..., description="Policy type")
    input_sources_id: str | None = Field(default=None, description="Condition ID to reference")

    # Absolute linear policy parameters
    base_freq: float | None = Field(default=None, description="Base frequency output at base_temp input")
    base_temp: float | None = Field(default=None, description="Base temperature (or other input value)")
    gain_hz_per_unit: float | None = Field(
        default=None, description="Frequency change per unit input change (Hz/°C, Hz/kPa, etc.)"
    )
    # Soft validation state flag
    invalid: bool = Field(default=False)

    @model_validator(mode="after")
    def validate_policy_requirements(self):
        """Validate policy-specific requirements"""
        problems = []

        # Linear policies require input reference
        if self.type in {ControlPolicyType.ABSOLUTE_LINEAR, ControlPolicyType.INCREMENTAL_LINEAR}:
            if not self.input_sources_id:
                problems.append(
                    f"{self.type.value} policy requires 'input_sources_id' field " f"(condition ID reference)"
                )

        # Absolute linear specific validations
        match self.type:
            case ControlPolicyType.ABSOLUTE_LINEAR:
                missing = []
                if self.base_freq is None:
                    missing.append("base_freq")
                if self.base_temp is None:
                    missing.append("base_temp")
                if self.gain_hz_per_unit is None:
                    missing.append("gain_hz_per_unit")

                if missing:
                    problems.append(f"absolute_linear policy requires: {', '.join(missing)}")
            case ControlPolicyType.INCREMENTAL_LINEAR:
                if self.gain_hz_per_unit is None:
                    problems.append("incremental_linear policy requires gain_hz_per_unit")
            case ControlPolicyType.DISCRETE_SETPOINT:
                if self.input_sources_id is not None:
                    logger.warning("[POLICY] discrete_setpoint policy does not use 'input_sources_id' field")

        if problems:
            for msg in problems:
                logger.warning(f"[POLICY] {msg}")
            object.__setattr__(self, "invalid", True)

        return self
