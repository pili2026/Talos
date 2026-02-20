from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.schema.config_metadata import ConfigMetadata


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
    INITIALIZATION: bool = Field(default=True)
    SNAPSHOT_SAVER: bool = Field(default=True)

    def __getitem__(self, key: str) -> bool:
        return getattr(self, key, True)

    def get(self, key: str, default: bool = False) -> bool:
        """Dict-like get method for compatibility."""
        return getattr(self, key, default)

    def items(self):
        return self.model_dump().items()

    def keys(self):
        return self.model_dump().keys()

    def values(self):
        return self.model_dump().values()

    def __iter__(self):
        return iter(self.model_dump())


class ReverseSshConfig(BaseModel):
    PORT_SOURCE: Literal["config", "mqtt"] = Field(
        default="config", description="Reverse SSH port source: config | mqtt"
    )
    PORT: int | None = Field(
        default=None, ge=1, le=65535, description="Reverse SSH port (only when PORT_SOURCE=config)"
    )


class RemoteAccessConfig(BaseModel):
    REVERSE_SSH: ReverseSshConfig = Field(default_factory=ReverseSshConfig)


class SystemConfig(BaseModel):
    """System configuration (full)"""

    model_config = ConfigDict(extra="allow")

    MONITOR_INTERVAL_SECONDS: float = Field(default=1.0, gt=0, description="Monitoring interval (seconds)")
    MONITOR_READ_CONCURRENCY: int = Field(
        default=50, ge=1, le=500, description="Max concurrent device read tasks in monitor loop."
    )
    MONITOR_DEVICE_TIMEOUT_SEC: float = Field(default=3.0, gt=0, le=60, description="Per-device read timeout seconds.")
    MONITOR_LOG_EACH_DEVICE: bool = Field(default=False, description="Log per-device online status (debug)")
    PATHS: PathsConfig = Field(default_factory=PathsConfig)
    DEVICE_ID_POLICY: DeviceIdPolicyConfig = Field(default_factory=DeviceIdPolicyConfig)
    SUBSCRIBERS: SubscribersConfig = Field(default_factory=SubscribersConfig)

    REMOTE_ACCESS: RemoteAccessConfig = Field(default_factory=RemoteAccessConfig)


class SystemConfigFileSchema(BaseModel):
    """
    system_config.yml schema for YAMLManager.
    Adds _metadata block for version control, backup, and checksum.
    Used only by SystemConfigService for reading/writing yml.
    Core continues to use SystemConfig (without metadata).
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    metadata: ConfigMetadata = Field(default_factory=ConfigMetadata, alias="_metadata")

    MONITOR_INTERVAL_SECONDS: float = Field(default=10.0, gt=0)
    MONITOR_READ_CONCURRENCY: int = Field(default=50, ge=1, le=500)
    MONITOR_DEVICE_TIMEOUT_SEC: float = Field(default=3.0, gt=0, le=60)
    MONITOR_LOG_EACH_DEVICE: bool = Field(default=False)
    PATHS: PathsConfig = Field(default_factory=PathsConfig)
    DEVICE_ID_POLICY: DeviceIdPolicyConfig = Field(default_factory=DeviceIdPolicyConfig)
    SUBSCRIBERS: SubscribersConfig = Field(default_factory=SubscribersConfig)
    REMOTE_ACCESS: RemoteAccessConfig = Field(default_factory=RemoteAccessConfig)
