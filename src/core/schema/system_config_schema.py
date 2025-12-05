from pydantic import BaseModel, ConfigDict, Field


class PathsConfig(BaseModel):
    """Path configuration"""

    STATE_DIR: str = Field(default="logs/state", description="State data directory")
    LOG_DIR: str = Field(default="logs", description="Log directory")


class DeviceIdPolicyConfig(BaseModel):
    """Device ID policy configuration (data only)"""

    SERIES: int = Field(default=0, ge=0, le=15, description="Series number")
    WIDTH: int = Field(default=3, ge=1, le=8, description="Width")
    RADIX: str = Field(default="hex", description="Number base (hex/dec)")
    UPPERCASE: bool = Field(default=True, description="Use uppercase")
    PREFIX: str = Field(default="", description="Prefix")


class SubscribersConfig(BaseModel):
    """Subscribers configuration"""

    MONITOR: bool = Field(default=True)
    TIME_CONTROL: bool = Field(default=True)
    CONSTRAINT: bool = Field(default=True)
    ALERT: bool = Field(default=True)
    ALERT_NOTIFIERS: bool = Field(default=True)
    CONTROL: bool = Field(default=True)
    DATA_SENDER: bool = Field(default=True)

    def __getitem__(self, key: str) -> bool:
        return getattr(self, key, True)


class SystemConfig(BaseModel):
    """System configuration (full)"""

    model_config = ConfigDict(
        extra="allow",
    )

    MONITOR_INTERVAL_SECONDS: float = Field(default=10.0, description="Monitoring interval (seconds)")
    PATHS: PathsConfig = Field(default_factory=PathsConfig)
    DEVICE_ID_POLICY: DeviceIdPolicyConfig = Field(default_factory=DeviceIdPolicyConfig)
    SUBSCRIBERS: SubscribersConfig = Field(default_factory=SubscribersConfig)
