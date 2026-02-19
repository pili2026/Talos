"""
Configuration Management Router
API endpoints for modbus device configuration
"""

from fastapi import APIRouter, Depends, HTTPException

from api.dependency import get_config_service, get_current_user
from api.model.modbus_config import (
    BackupListResponse,
    ConfigUpdateResponse,
    MetadataResponse,
    ModbusBusCreateRequest,
    ModbusConfigResponse,
    ModbusDeviceCreateRequest,
    ModbusDeviceInfo,
)
from api.service.modbus_config_service import ConfigService

router = APIRouter()


# ============================================================================
# Metadata Endpoints
# ============================================================================


@router.get("/metadata", response_model=MetadataResponse, summary="Get configuration metadata")
async def get_metadata(config_service: ConfigService = Depends(get_config_service)) -> MetadataResponse:
    """Get modbus device configuration metadata (generation, checksum, etc.)"""
    return await config_service.get_metadata()


# ============================================================================
# Configuration Endpoints
# ============================================================================


@router.get("", response_model=ModbusConfigResponse, summary="Get complete modbus configuration")
async def get_config(config_service: ConfigService = Depends(get_config_service)) -> ModbusConfigResponse:
    """Get all modbus buses and devices with metadata"""
    return await config_service.get_config()


# ============================================================================
# Bus Endpoints
# ============================================================================


@router.post("/buses/{bus_name}", response_model=ConfigUpdateResponse, summary="Create or update modbus bus")
async def create_or_update_bus(
    bus_name: str,
    bus_request: ModbusBusCreateRequest,
    config_service: ConfigService = Depends(get_config_service),
    current_user: str = Depends(get_current_user),
) -> ConfigUpdateResponse:
    """Create or update a modbus bus configuration"""
    return await config_service.create_or_update_bus(bus_name, bus_request, current_user)


@router.delete("/buses/{bus_name}", response_model=ConfigUpdateResponse, summary="Delete modbus bus")
async def delete_bus(
    bus_name: str,
    config_service: ConfigService = Depends(get_config_service),
    current_user: str = Depends(get_current_user),
) -> ConfigUpdateResponse:
    """Delete a modbus bus (fails if devices are using it)"""
    return await config_service.delete_bus(bus_name, current_user)


# ============================================================================
# Device Endpoints
# ============================================================================


@router.post("/devices", response_model=ConfigUpdateResponse, summary="Create or update modbus device")
async def create_or_update_device(
    device_request: ModbusDeviceCreateRequest,
    config_service: ConfigService = Depends(get_config_service),
    current_user: str = Depends(get_current_user),
) -> ConfigUpdateResponse:
    """
    Create or update a modbus device configuration

    Validates that slave_id is unique within the same bus.
    Raises 400 if duplicate (bus, slave_id) combination is detected.
    """
    modbus_config_response: ModbusConfigResponse = await config_service.get_config()

    existing_device = None
    for device in modbus_config_response.devices:
        if device.model == device_request.model and device.slave_id == device_request.slave_id:
            existing_device = device
            break

    for device in modbus_config_response.devices:
        if existing_device and device.model == existing_device.model and device.slave_id == existing_device.slave_id:
            continue

        if device.bus == device_request.bus and device.slave_id == device_request.slave_id:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "duplicate_slave_id",
                    "message": f"Slave ID {device_request.slave_id} already exists on bus '{device_request.bus}'",
                    "bus": device_request.bus,
                    "slave_id": device_request.slave_id,
                    "existing_device": {
                        "model": device.model,
                        "display_name": _get_device_display_name(device),
                    },
                },
            )

    return await config_service.create_or_update_device(device_request, current_user)


@router.delete("/devices/{model}/{slave_id}", response_model=ConfigUpdateResponse, summary="Delete modbus device")
async def delete_device(
    model: str,
    slave_id: int,
    config_service: ConfigService = Depends(get_config_service),
    current_user: str = Depends(get_current_user),
) -> ConfigUpdateResponse:
    """Delete a modbus device by model and slave_id"""
    return await config_service.delete_device(model, slave_id, current_user)


# ============================================================================
# Backup Endpoints
# ============================================================================


@router.get("/backups", response_model=BackupListResponse, summary="List configuration backups")
async def list_backups(config_service: ConfigService = Depends(get_config_service)) -> BackupListResponse:
    """Get list of available backup files"""
    return await config_service.list_backups()


@router.post("/backups/{filename}/restore", response_model=ConfigUpdateResponse, summary="Restore from backup")
async def restore_backup(
    filename: str,
    config_service: ConfigService = Depends(get_config_service),
    current_user: str = Depends(get_current_user),
) -> ConfigUpdateResponse:
    """Restore configuration from a backup file"""
    return await config_service.restore_backup(filename, current_user)


# ============================================================================
# Helper Functions
# ============================================================================


def _get_device_display_name(device: ModbusDeviceInfo) -> str:
    """
    Get display name for a device.

    Priority: modes.name > f"{model}_{slave_id}"
    """
    if device.modes and isinstance(device.modes, dict):
        name = device.modes.get("name")
        if name:
            return str(name)

    return f"{device.model}_{device.slave_id}"
