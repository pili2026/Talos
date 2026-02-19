"""
Configuration Management API Models
Request and Response models for modbus device configuration
"""

from typing import Any

from pydantic import BaseModel, Field

from api.model.responses import BaseResponse

# ============================================================================
# Request Models
# ============================================================================


class ModbusDeviceCreateRequest(BaseModel):
    """Request model for creating/updating a modbus device"""

    model: str = Field(..., description="Device model name (e.g., 'ADTEK_CPM10')")
    type: str = Field(..., description="Device type (e.g., 'power_meter', 'vfd')")
    model_file: str = Field(..., description="Path to driver YAML file")
    slave_id: int = Field(..., ge=1, le=247, description="Modbus slave ID (1-247)")
    bus: str = Field(..., description="Bus reference name (e.g., 'rtu0')")
    modes: dict[str, Any] = Field(default_factory=dict, description="Device operation modes")


class ModbusBusCreateRequest(BaseModel):
    """Request model for creating/updating a modbus bus"""

    port: str = Field(..., description="Serial port path")
    baudrate: int = Field(default=9600, description="Baud rate")
    timeout: float = Field(default=1.0, gt=0, le=2.0, description="Modbus timeout in seconds")


# ============================================================================
# Response Models
# ============================================================================


class MetadataInfo(BaseModel):
    """Configuration metadata information"""

    generation: int = Field(..., description="Current generation number")
    source: str = Field(..., description="Last modification source (cloud/edge/manual)")
    last_modified: str = Field(..., description="Last modification timestamp (ISO 8601)")
    last_modified_by: str | None = Field(None, description="User/system that made the modification")
    checksum: str | None = Field(None, description="SHA256 checksum")
    applied_at: str | None = Field(None, description="When configuration was applied")
    cloud_sync_id: str | None = Field(None, description="Cloud sync identifier")


class ModbusDeviceInfo(BaseModel):
    """Modbus device information"""

    model: str
    type: str
    model_file: str
    slave_id: int
    bus: str | None = None
    port: str | None = None
    baudrate: int | None = None
    timeout: float | None = None
    modes: dict[str, Any] = Field(default_factory=dict)


class ModbusBusInfo(BaseModel):
    """Modbus bus information"""

    name: str
    port: str
    baudrate: int
    timeout: float


class BackupInfo(BaseModel):
    """Backup file information"""

    filename: str
    generation: int | None = None
    created_at: str
    size_bytes: int


# ============================================================================
# API Response Models (using BaseResponse pattern)
# ============================================================================


class MetadataResponse(BaseResponse):
    """Response for configuration metadata"""

    metadata: MetadataInfo


class ModbusConfigResponse(BaseResponse):
    """Response for complete modbus configuration"""

    metadata: MetadataInfo
    buses: dict[str, ModbusBusInfo]
    devices: list[ModbusDeviceInfo]


class ConfigUpdateResponse(BaseResponse):
    """Response for configuration update operations"""

    generation: int = Field(..., description="New generation number")
    checksum: str = Field(..., description="New checksum")
    modified_at: str = Field(..., description="Modification timestamp")


class BackupListResponse(BaseResponse):
    """Response for backup list"""

    backups: list[BackupInfo]
    total: int
