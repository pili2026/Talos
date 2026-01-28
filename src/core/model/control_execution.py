"""
Control Execution Models

Runtime models for control execution logic.
These are model-layer objects used for business logic,
not persisted to database.
"""

from pydantic import BaseModel, ConfigDict, Field

from core.model.device_constant import VALUE_TOLERANCE


class WrittenTarget(BaseModel):
    """
    Record of a register write operation.

    Used for priority protection in ControlExecutor to prevent
    lower priority actions from overwriting higher priority writes.

    Lifecycle: Single execution cycle (method-scoped)
    Layer: Model (business logic)

    Attributes:
        value: The value that was written to the register
        priority: Priority of the action that wrote this value (lower number = higher priority)
        rule_code: Code/identifier of the rule that triggered this write

    Example:
        >>> written = WrittenTarget(value=50.0, priority=10, rule_code="TEMP_CTRL_01")
        >>> written.value
        50.0
        >>> written.priority
        10
    """

    model_config = ConfigDict(
        frozen=True,  # Immutable after creation
        str_strip_whitespace=True,  # Auto-trim rule_code
        validate_assignment=True,  # Validate on field assignment (though frozen prevents this)
    )

    value: float | int = Field(..., description="Value that was written to the register", examples=[50.0, 60, 1])

    priority: int = Field(
        ...,
        description="Priority of the action that wrote this value (lower = higher priority)",
        ge=0,  # Priority must be non-negative
        examples=[10, 20, 100],
    )

    rule_code: str = Field(
        ...,
        description="Code/identifier of the rule that triggered this write",
        min_length=1,  # Rule code cannot be empty
        examples=["TEMP_CTRL_01", "EMERGENCY_STOP", "COOLING_LOOP_A"],
    )

    def has_higher_priority_than(self, other_priority: int) -> bool:
        """Check if this write has higher priority than given priority"""
        return self.priority < other_priority

    def conflicts_with(self, new_value: float | int, tolerance: float = VALUE_TOLERANCE) -> bool:
        if isinstance(self.value, (int, float)) and isinstance(new_value, (int, float)):
            return abs(float(self.value) - float(new_value)) > tolerance
        return self.value != new_value

    def __str__(self) -> str:
        """Human-readable representation"""
        return f"WrittenTarget(value={self.value}, priority={self.priority}, rule={self.rule_code})"

    def __repr__(self) -> str:
        """Developer-friendly representation"""
        return (
            f"WrittenTarget("
            f"value={self.value!r}, "
            f"priority={self.priority!r}, "
            f"rule_code={self.rule_code!r}"
            f")"
        )
