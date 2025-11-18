"""
Device Constraints Router

Defines all API endpoints related to device constraint management.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependency import get_constraint_service
from api.model.responses import DeviceConstraintResponse
from api.service.constraint_service import ConstraintService

router = APIRouter()


@router.get(
    "/",
    response_model=list[DeviceConstraintResponse],
    summary="Get all device constraints",
    description="Return constraint information (min/max limits) for all configured devices",
)
async def list_all_constraints(
    service: ConstraintService = Depends(get_constraint_service),
) -> list[DeviceConstraintResponse]:
    """
    Retrieve constraints for all devices.

    Returns:
        list[DeviceConstraintResponse]: List of constraint information for all devices.
    """
    constraints = await service.get_all_device_constraints()
    return constraints


@router.get(
    "/{device_id}",
    response_model=DeviceConstraintResponse,
    summary="Get specific device constraints",
    description="Return constraint information (min/max limits) for a specific device by its ID",
)
async def get_device_constraints(
    device_id: str,
    service: ConstraintService = Depends(get_constraint_service),
) -> DeviceConstraintResponse:
    """
    Retrieve constraint information for a specific device.

    Args:
        device_id: Unique device identifier (format: model_slaveId).

    Returns:
        DeviceConstraintResponse: Device constraint information.

    Raises:
        HTTPException: Raised with 404 if the device is not found.
    """
    constraints = await service.get_device_constraints(device_id)

    if not constraints:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Device '{device_id}' not found or has no constraints",
        )

    return constraints
