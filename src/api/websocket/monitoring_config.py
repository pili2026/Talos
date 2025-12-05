"""
Configuration for WebSocket monitoring service.
Centralizes all configurable parameters for monitoring behavior.

Uses Pydantic for validation and YAML configuration support,
consistent with Talos system architecture.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MonitoringConfig(BaseModel):
    """
    Configuration for WebSocket monitoring behavior.

    Uses Pydantic for validation and configuration management,
    consistent with Talos configuration patterns.

    All timing and threshold parameters are centralized here
    for easy adjustment and testing.

    Example:
        >>> config = MonitoringConfig()
        >>> config.max_consecutive_failures
        3

        >>> config = MonitoringConfig(max_consecutive_failures=5)
        >>> config.validate_interval(1.5)
        True
    """

    model_config = ConfigDict(
        validate_assignment=True,  # Validate on attribute assignment
        extra="forbid",  # Forbid extra fields
        frozen=False,  # Allow modification after creation
    )

    # Connection health monitoring
    max_consecutive_failures: int = Field(
        default=3,
        ge=1,
        description="Maximum consecutive failures before closing connection",
    )

    # Default intervals (seconds)
    default_single_device_interval: float = Field(
        default=1.0,
        gt=0,
        description="Default update interval for single device monitoring (seconds)",
    )

    default_multi_device_interval: float = Field(
        default=2.0,
        gt=0,
        description="Default update interval for multi-device monitoring (seconds)",
    )

    # Interval constraints
    min_interval: float = Field(
        default=0.5,
        gt=0,
        description="Minimum allowed update interval (seconds)",
    )

    max_interval: float = Field(
        default=60.0,
        gt=0,
        description="Maximum allowed update interval (seconds)",
    )

    # Feature flags
    enable_control_commands: bool = Field(
        default=True,
        description="Whether to enable device control via WebSocket",
    )

    @field_validator("max_interval")
    @classmethod
    def validate_max_greater_than_min(cls, v, info):
        """Ensure max_interval is greater than min_interval."""
        if "min_interval" in info.data:
            min_interval = info.data["min_interval"]
            if v <= min_interval:
                raise ValueError(f"max_interval ({v}) must be greater than min_interval ({min_interval})")
        return v

    @model_validator(mode="after")
    def validate_default_intervals(self):
        """Ensure default intervals are within min/max bounds."""
        if not (self.min_interval <= self.default_single_device_interval <= self.max_interval):
            raise ValueError(
                f"default_single_device_interval ({self.default_single_device_interval}) "
                f"must be between {self.min_interval} and {self.max_interval}"
            )

        if not (self.min_interval <= self.default_multi_device_interval <= self.max_interval):
            raise ValueError(
                f"default_multi_device_interval ({self.default_multi_device_interval}) "
                f"must be between {self.min_interval} and {self.max_interval}"
            )

        return self

    def validate_interval(self, interval: float) -> bool:
        """
        Check if an interval is within allowed bounds.

        Args:
            interval: Interval to validate in seconds

        Returns:
            True if valid, False otherwise

        Example:
            >>> config = MonitoringConfig()
            >>> config.validate_interval(1.0)
            True
            >>> config.validate_interval(0.1)
            False
        """
        return self.min_interval <= interval <= self.max_interval


class WebSocketLimits(BaseModel):
    """
    WebSocket connection limits and constraints.

    Uses Pydantic for validation, consistent with Talos patterns.
    Used for rate limiting and resource management.

    Example:
        >>> limits = WebSocketLimits()
        >>> limits.max_active_connections
        100
    """

    model_config = ConfigDict(
        validate_assignment=True,
        extra="forbid",
        frozen=False,
    )

    max_active_connections: int = Field(
        default=100,
        ge=1,
        description="Maximum number of concurrent WebSocket connections",
    )

    max_devices_per_connection: int = Field(
        default=20,
        ge=1,
        description="Maximum number of devices in multi-device monitoring",
    )

    max_parameters_per_device: int = Field(
        default=50,
        ge=1,
        description="Maximum number of parameters to monitor per device",
    )

    # Timeouts (seconds)
    connection_timeout: float = Field(
        default=30.0,
        gt=0,
        description="Timeout for initial connection establishment (seconds)",
    )

    read_timeout: float = Field(
        default=5.0,
        gt=0,
        description="Timeout for parameter read operations (seconds)",
    )

    write_timeout: float = Field(
        default=5.0,
        gt=0,
        description="Timeout for parameter write operations (seconds)",
    )

    # Message size limits
    max_message_size: int = Field(
        default=1024 * 1024,  # 1MB
        ge=1024,  # At least 1KB
        description="Maximum WebSocket message size in bytes",
    )


# Global default configuration
DEFAULT_CONFIG = MonitoringConfig()

# Global limits configuration
DEFAULT_LIMITS = WebSocketLimits()
