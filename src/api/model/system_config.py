"""
System Config API Models
"""

from pydantic import BaseModel, Field


class SystemConfigUpdateRequest(BaseModel):
    """Request model for updating system config"""

    monitor_interval_seconds: float = Field(..., gt=0, le=3600, description="Monitor interval in seconds")

    control_interval_seconds: float | None = Field(
        default=None, gt=0, le=3600, description="Control interval in seconds"
    )
    alert_interval_seconds: float | None = Field(default=None, gt=0, le=3600, description="Alert interval in seconds")

    device_id_series: int = Field(default=0, ge=0, le=9, description="Device ID policy series (0-9)")


class SystemConfigInfo(BaseModel):
    """Current system config (user-editable fields)"""

    monitor_interval_seconds: float

    control_interval_seconds: float | None = None
    alert_interval_seconds: float | None = None

    device_id_series: int
    reverse_ssh_port: int
    reverse_ssh_port_source: str = Field(description="Where the port value was read from: 'service' or 'config'")


class SystemConfigResponse(BaseModel):
    status: str
    config: SystemConfigInfo


class SystemConfigUpdateResponse(BaseModel):
    status: str
    message: str
