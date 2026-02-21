"""
System Config Router
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependency import get_system_config_service
from api.model.common import BackupListResponse
from api.model.system_config import SystemConfigResponse, SystemConfigUpdateRequest, SystemConfigUpdateResponse
from api.service.system_config_service import SystemConfigService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=SystemConfigResponse, summary="Get system configuration")
async def get_system_config(
    service: SystemConfigService = Depends(get_system_config_service),
) -> SystemConfigResponse:
    """Get current user-editable system configuration."""
    try:
        return service.get_config()
    except Exception as e:
        logger.error(f"Failed to get system config: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


@router.post("", response_model=SystemConfigUpdateResponse, summary="Update system configuration")
async def update_system_config(
    req: SystemConfigUpdateRequest,
    service: SystemConfigService = Depends(get_system_config_service),
) -> SystemConfigUpdateResponse:
    """Update user-editable system configuration and regenerate yml."""
    try:
        return service.update_config(req)
    except Exception as e:
        logger.error(f"Failed to update system config: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e
