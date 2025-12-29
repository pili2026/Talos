"""
Device Management Router

Defines all API endpoints related to device management.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependency import get_device_service
from api.model.enums import DeviceConnectionStatus, ResponseStatus
from api.model.responses import DeviceInfo, DeviceListResponse
from api.service.device_service import DeviceService

router = APIRouter()

logger = logging.getLogger("DeviceRouter")


@router.get(
    "/",
    response_model=DeviceListResponse,
    summary="Get all devices",
    description="Return a list of all configured devices in the system along with their status",
)
async def list_devices(
    include_status: bool = False, service: DeviceService = Depends(get_device_service)
) -> DeviceListResponse:
    """
    Retrieve a list of all devices.

    Args:
        include_status: Whether to check actual device connectivity (default: False)

    Returns:
        DeviceListResponse: Response containing all device information.
    """
    try:
        devices = await service.get_all_devices(include_status=include_status)
        return DeviceListResponse(status=ResponseStatus.SUCCESS, devices=devices, total_count=len(devices))
    except Exception as e:
        logger.error(f"Error listing devices: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get(
    "/{device_id}",
    response_model=DeviceInfo,
    summary="Get specific device information",
    description="Return detailed information of a specific device by its ID",
)
async def get_device(
    device_id: str,
    include_status: bool = True,
    service: DeviceService = Depends(get_device_service),
) -> DeviceInfo:
    """
    Retrieve detailed information for a specific device.

    Args:
        device_id: Unique device identifier.
        include_status: Whether to check actual device connectivity (default: True)

    Returns:
        DeviceInfo: Detailed device information.

    Raises:
        HTTPException: Raised with 404 if the device is not found.
    """
    try:
        device = await service.get_device_by_id(device_id, include_status=include_status)
        if not device:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Device '{device_id}' not found")
        return device
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting device {device_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


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
    try:
        status_enum = await service.check_device_connectivity(device_id)

        # TODO: Make Response Model
        return {
            "device_id": device_id,
            "connection_status": status_enum.value,
            "is_online": status_enum == DeviceConnectionStatus.ONLINE,
        }
    except Exception as e:
        logger.error(f"Error checking connectivity for {device_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


# api/router/device_router.py


@router.get(
    "/{device_id}/health",
    summary="Get device health status",
    description=(
        "Get device health status from DeviceHealthManager. "
        "This explains why AsyncDeviceMonitor might return -1 values even when the device is actually online."
    ),
)
async def get_device_health(device_id: str, service: DeviceService = Depends(get_device_service)) -> dict:
    """
    Get device health status tracked by DeviceHealthManager.

    **Important difference from /connectivity:**

    - **/connectivity**: Tests if device responds RIGHT NOW (direct Modbus communication)
    - **/health**: Shows if DeviceHealthManager considers the device healthy

    **Common scenario:**

    If a device shows:
    - `connectivity` = "online" (device can communicate)
    - `health.is_healthy` = false (health manager considers it unhealthy)

    This explains why **AsyncDeviceMonitor returns -1 values**:
    - The device is physically working and can respond to direct reads
    - But health manager has it in cooldown after previous failures
    - Monitor skips polling until the next recovery window

    **Use this endpoint to:**
    - Debug why monitor shows -1 when device is actually online
    - Check how long until next recovery attempt (cooldown_remaining_sec)
    - See the failure history (consecutive_failures, last_failure_ts)

    Args:
        device_id: Device identifier (format: "MODEL_SLAVEID")

    Returns:
        Health status information including:
        - is_healthy: Whether device is considered healthy
        - consecutive_failures: Number of consecutive failures
        - cooldown_remaining_sec: Seconds until next poll attempt
        - explanation: Human-readable explanation of the status
    """
    try:
        health_status = await service.get_device_health_status(device_id)

        if "error" in health_status:
            if "not registered" in health_status.get("error", ""):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=health_status["error"])
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=health_status["error"])

        return health_status

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting health status for {device_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get(
    "/health/summary",
    summary="Get health summary for all devices",
    description="Get aggregated health information for all devices in the system",
)
async def get_all_devices_health_summary(service: DeviceService = Depends(get_device_service)) -> dict:
    """
    Get health summary for all devices.

    Useful for:
    - Dashboard overview of system health
    - Identifying all unhealthy devices at once
    - Monitoring overall system status

    Returns:
        Summary containing:
        - total_devices: Total number of devices
        - healthy_count: Number of healthy devices
        - unhealthy_count: Number of unhealthy devices
        - unhealthy_devices: List of unhealthy device IDs
        - devices: Detailed status for each device
    """
    try:
        summary = await service.get_all_devices_health_summary()

        if "error" in summary:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=summary["error"])

        return summary

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting health summary: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e
