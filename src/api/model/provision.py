from pydantic import BaseModel, Field, field_validator


class SetConfigRequest(BaseModel):
    """Request model for setting system configuration"""

    hostname: str = Field(
        ..., min_length=11, max_length=11, description="System hostname (exactly 11 alphanumeric characters)"
    )
    reverse_port: int = Field(..., ge=1024, le=65535, description="Reverse SSH port")

    @field_validator("hostname")
    @classmethod
    def validate_hostname_format(cls, v: str) -> str:
        """Validate hostname contains only alphanumeric characters"""
        if not v.isalnum():
            raise ValueError("Hostname can only contain letters and numbers")
        return v


class ProvisionCurrentConfig(BaseModel):
    """Current system configuration"""

    hostname: str = Field(..., description="Current system hostname")
    reverse_port: int = Field(..., description="Current reverse SSH port")
    port_source: str = Field(..., description="Port source: 'service' or 'config'")


class ProvisionSetConfigResult(BaseModel):
    """Result of set configuration operation"""

    success: bool = Field(..., description="Whether operation succeeded")
    requires_reboot: bool = Field(..., description="Whether system reboot is required")
    changes: list[str] = Field(default_factory=list, description="List of changes made")
    message: str = Field(..., description="Result message")


class ProvisionRebootResult(BaseModel):
    """Result of reboot operation"""

    success: bool = Field(..., description="Whether reboot was triggered")
    message: str = Field(..., description="Result message")
