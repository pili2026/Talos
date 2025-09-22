import logging

from pydantic import BaseModel, Field, field_validator, model_validator

from model.enum.condition_enum import ConditionType, ControlPolicyType

logger = logging.getLogger(__name__)


class PolicyConfig(BaseModel):
    """
    Control Policy (child level):
    - discrete_setpoint: discrete fixed value (backward compatible, Evaluator can directly use action.value)
    - absolute_linear: map input linearly to an "absolute frequency"; Evaluator computes and overwrites action.value
    - incremental_linear: compute "delta Hz" from input; Executor must implement adjust_frequency
    Validation principle: never raise; instead, log warnings + mark invalid=True, leaving filtering to the parent level.
    """

    type: ControlPolicyType

    # Input sources
    condition_type: ConditionType = ConditionType.SINGLE
    source: str | None = None  # used for "single"
    sources: list[str] | None = None  # used for "difference" (>=2 required)
    abs: bool = False  # whether to take absolute value in difference mode

    # Deadband / clamp (applicable to both linear types)
    deadband: float = 0.0
    min_freq: float | None = None
    max_freq: float | None = None

    # absolute_linear specific
    base_freq: float | None = None
    gain_hz_per_unit: float | None = None

    # incremental_linear specific
    max_step_hz: float | None = None

    # Soft validation flag
    invalid: bool = Field(default=False)

    @field_validator("sources")
    @classmethod
    def _normalize_sources(cls, v):
        if v is None:
            return None
        vv = [str(s).strip() for s in v if str(s).strip()]
        return vv or None

    @model_validator(mode="after")
    def _soft_semantic_checks(self):
        problems: list[str] = []

        # Source checks
        if self.condition_type == ConditionType.SINGLE:
            if not self.source:
                problems.append("policy.source required when source_kind='single'")
        else:  # difference
            if not self.sources or len(self.sources) < 2:
                problems.append("policy.sources (>=2) required when source_kind='difference'")

        # Policy-specific requirements
        if self.type == ControlPolicyType.ABSOLUTE_LINEAR:
            if self.base_freq is None:
                problems.append("absolute_linear requires policy.base_freq")
            if self.gain_hz_per_unit is None:
                problems.append("absolute_linear requires policy.gain_hz_per_unit")

        if self.type == ControlPolicyType.INCREMENTAL_LINEAR:
            if self.gain_hz_per_unit is None:
                problems.append("incremental_linear requires policy.gain_hz_per_unit")
            if self.max_step_hz is not None and self.max_step_hz <= 0:
                problems.append("policy.max_step_hz, if provided, must be > 0")

        # Clamp checks
        if self.min_freq is not None and self.max_freq is not None:
            if self.min_freq > self.max_freq:
                problems.append("policy.min_freq must be <= policy.max_freq")

        if problems:
            logger.warning(f"[POLICY] invalid policy: {problems}")
            object.__setattr__(self, "invalid", True)

        return self
