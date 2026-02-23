"""
Instance Config Router
Manages device_instance_config.yml via REST API
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependency import get_instance_config_service
from api.model.instance_config import (
    DeviceConfigRequest,
    InstanceConfigRequest,
    InstanceConfigResponse,
    UpdateDeviceConfigRequest,
)
from api.service.instance_config_service import InstanceConfigService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=InstanceConfigResponse, summary="Get full instance config")
async def get_instance_config(
    service: InstanceConfigService = Depends(get_instance_config_service),
) -> InstanceConfigResponse:
    try:
        return service.get_config()
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/{model}", response_model=DeviceConfigRequest, summary="Get config for a specific device model")
async def get_device_config(
    model: str,
    service: InstanceConfigService = Depends(get_instance_config_service),
) -> DeviceConfigRequest:
    try:
        return service.get_device_config(model)
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.put("/{model}", response_model=InstanceConfigResponse, summary="Update config for a specific device model")
async def update_device_config(
    model: str,
    request: UpdateDeviceConfigRequest,
    service: InstanceConfigService = Depends(get_instance_config_service),
) -> InstanceConfigResponse:
    try:
        return service.update_device_config(model, request)
    except Exception as e:
        logger.error(f"[instance_config] Failed to update model='{model}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e


@router.put(
    "/{model}/{slave_id}", response_model=InstanceConfigResponse, summary="Update config for a specific device instance"
)
async def update_instance_config(
    model: str,
    slave_id: str,
    request: InstanceConfigRequest,
    service: InstanceConfigService = Depends(get_instance_config_service),
) -> InstanceConfigResponse:
    try:
        return service.update_instance(model, slave_id, request)
    except Exception as e:
        logger.error(f"[instance_config] Failed to update model='{model}' slave_id='{slave_id}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e
