from pydantic import BaseModel, Field, field_validator

from core.model.enum.health_check_strategy_enum import HealthCheckStrategyEnum
from core.model.enum.register_type_enum import RegisterType


class HealthCheckConfig(BaseModel):
    """
    Health check configuration for a device model.

    Examples:
        # Single register strategy (VFD)
        strategy: single_register
        register: INVSTATUS
        register_type: holding
        timeout_sec: 0.6

        # Partial bulk strategy (AI module)
        strategy: partial_bulk
        registers: [AIn01, AIn02, AIn03]
        register_type: holding
        timeout_sec: 0.8

        # Full read strategy (complex devices)
        strategy: full_read
    """

    strategy: HealthCheckStrategyEnum = Field(
        default=HealthCheckStrategyEnum.SINGLE_REGISTER, description="Health check strategy type"
    )

    # Partial bulk mode
    registers: list[str] | None = Field(default=None, description="Register names for partial_bulk strategy")

    # Modbus register type
    register_type: RegisterType = Field(default=RegisterType.HOLDING, description="Modbus register type")

    # Retry and timeout
    retry_on_failure: int = Field(default=1, ge=0, le=3, description="Number of retries on failure (0-3)")

    timeout_sec: float = Field(
        default=1.0, gt=0, le=3.0, description="asyncio timeout for health check (must be > modbus client timeout)"
    )

    # Optional metadata
    reason: str | None = Field(default=None, description="Explanation for this strategy choice")

    @field_validator("registers")
    def validate_partial_bulk_mode(cls, v, info):
        """Validate that registers is provided when strategy is partial_bulk"""
        strategy = info.data.get("strategy")
        if strategy == HealthCheckStrategyEnum.PARTIAL_BULK:
            if not v:
                raise ValueError("registers must be provided when strategy is partial_bulk")
            if len(v) < 1 or len(v) > 5:
                raise ValueError("registers must contain 1-5 register names")
        return v

    @field_validator("timeout_sec")
    def validate_timeout_reasonable(cls, v):
        """Warn if timeout is very small"""
        if v < 0.3:
            raise ValueError("timeout_sec should be >= 0.3s to avoid false negatives")
        return v

    def to_summary(self) -> dict:
        """Convert to summary dict for logging"""
        summary = {
            "strategy": self.strategy.value,
            "register_type": self.register_type.value,
            "retry": self.retry_on_failure,
            "timeout": self.timeout_sec,
        }

        if self.strategy == HealthCheckStrategyEnum.SINGLE_REGISTER:
            summary["registers"] = self.registers[0] if self.registers else None
        elif self.strategy == HealthCheckStrategyEnum.PARTIAL_BULK:
            summary["registers"] = self.registers
            summary["count"] = len(self.registers) if self.registers else 0

        return summary
