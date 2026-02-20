"""
Shared API Models
Common models reused across multiple config domains
"""

from pydantic import BaseModel, Field

from api.model.responses import BaseResponse


class MetadataInfo(BaseModel):
    """Configuration metadata information"""

    generation: int = Field(..., description="Current generation number")
    source: str = Field(..., description="Last modification source (cloud/edge/manual)")
    last_modified: str = Field(..., description="Last modification timestamp (ISO 8601)")
    last_modified_by: str | None = Field(None, description="User/system that made the modification")
    checksum: str | None = Field(None, description="SHA256 checksum")
    applied_at: str | None = Field(None, description="When configuration was applied")
    cloud_sync_id: str | None = Field(None, description="Cloud sync identifier")


class MetadataResponse(BaseResponse):
    """Response for configuration metadata"""

    metadata: MetadataInfo


class ConfigUpdateResponse(BaseResponse):
    """Response for configuration update operations"""

    generation: int = Field(..., description="New generation number")
    checksum: str = Field(..., description="New checksum")
    modified_at: str = Field(..., description="Modification timestamp")


class BackupInfo(BaseModel):
    """Backup file information"""

    filename: str
    generation: int | None = None
    created_at: str
    size_bytes: int


class BackupListResponse(BaseResponse):
    """Response for backup list"""

    backups: list[BackupInfo]
    total: int
