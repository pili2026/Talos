"""
Device Management Router

Defines all API endpoints related to device management.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependency import get_device_service
from api.model.enums import DeviceConnectionStatus, ResponseStatus
from api.model.responses import DeviceInfo, DeviceListResponse
from api.service.device_service import DeviceService

router = APIRouter()


@router.get(
    "/",
    response_model=DeviceListResponse,
    summary="Get all devices",
    description="Return a list of all configured devices in the system along with their status",
)
async def list_devices(service: DeviceService = Depends(get_device_service)) -> DeviceListResponse:
    """
    Retrieve a list of all devices.

    Returns:
        DeviceListResponse: Response containing all device information.
    """
    devices = await service.get_all_devices()

    return DeviceListResponse(status=ResponseStatus.SUCCESS, devices=devices, total_count=len(devices))


@router.get(
    "/{device_id}",
    response_model=DeviceInfo,
    summary="Get specific device information",
    description="Return detailed information of a specific device by its ID",
)
async def get_device(device_id: str, service: DeviceService = Depends(get_device_service)) -> DeviceInfo:
    """
    Retrieve detailed information for a specific device.

    Args:
        device_id: Unique device identifier.

    Returns:
        DeviceInfo: Detailed device information.

    Raises:
        HTTPException: Raised with 404 if the device is not found.
    """
    device = await service.get_device_by_id(device_id)

    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Device '{device_id}' not found")

    return device


@router.get(
    "/{device_id}/connectivity",
    summary="Check device connectivity",
    description="Test whether the connection to the specified device is functioning properly",
)
async def check_connectivity(device_id: str, service: DeviceService = Depends(get_device_service)) -> dict:
    """
    Check the connection status of a device.

    Args:
        device_id: Device identifier.

    Returns:
        dict: Dictionary containing connection status information.
    """
    status_enum = await service.check_device_connectivity(device_id)

    return {
        "device_id": device_id,
        "connection_status": status_enum.value,
        "is_online": status_enum == DeviceConnectionStatus.ONLINE,
    }
