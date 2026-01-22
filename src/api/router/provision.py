import logging

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependency import get_provision_service
from api.model.provision import (
    ProvisionCurrentConfig,
    ProvisionRebootResult,
    ProvisionSetConfigResult,
    SetConfigRequest,
)
from api.service.provision_service import ProvisionService

logger = logging.getLogger("ProvisionRouter")

router = APIRouter()


@router.get("/config", response_model=ProvisionCurrentConfig)
async def get_config(service: ProvisionService = Depends(get_provision_service)):
    """
    Get current system configuration

    Returns current hostname and reverse SSH port.
    """
    try:
        return service.get_current_config()

    except Exception as e:
        logger.error(f"Failed to get config: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


@router.post("/config", response_model=ProvisionSetConfigResult)
async def set_config(req: SetConfigRequest, service: ProvisionService = Depends(get_provision_service)):
    """
    Update system configuration

    Updates hostname and/or reverse SSH port.
    Note: Hostname changes require system reboot to take effect.
    """
    try:
        return await service.set_config(req.hostname, req.reverse_port)

    except ValueError as e:
        # Validation error
        logger.warning(f"Validation error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    except Exception as e:
        logger.error(f"Failed to set config: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


@router.post("/reboot", response_model=ProvisionRebootResult)
async def trigger_reboot(service: ProvisionService = Depends(get_provision_service)):
    """
    Trigger system reboot

    Warning: This will immediately reboot the system.
    """
    try:
        return await service.trigger_reboot()

    except Exception as e:
        logger.error(f"Failed to trigger reboot: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e
