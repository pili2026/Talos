"""
Batch Operation Router

Handles batch read/write operations across multiple devices.
Provides efficient concurrent processing.

Design principles:
- Automatically adapts to different device models
- Gracefully handles parameters that don’t exist
- Distinguishes between skipped (expected) and failed (error)
- Provides detailed operational feedback
"""

import asyncio
import logging
from typing import Any, Set

from fastapi import APIRouter, Depends

from api.dependency import get_parameter_service
from api.model.requests import (
    BatchReadAllRequest,
    BatchReadDevicesRequest,
    BatchValidateRequest,
    BatchWriteMultipleRequest,
    BatchWriteRequest,
)
from api.model.responses import ResponseStatus
from api.repository.config_repository import ConfigRepository
from api.repository.modbus_repository import ModbusRepository
from api.service.parameter_service import ParameterService

router = APIRouter()
logger = logging.getLogger(__name__)


# ===== API Endpoints =====


@router.post(
    "/read",
    summary="Batch read across devices",
    description="Read specified parameters from multiple devices; automatically filters out parameters not present on each device.",
)
async def batch_read_devices(
    request: BatchReadDevicesRequest, service: ParameterService = Depends(get_parameter_service)
) -> dict[str, Any]:
    """
    Batch read parameters from multiple devices.

    Features:
    - Supports mixed device models
    - Automatically filters out non-existent parameters per device
    - Returns only parameters actually available on the device
    - Provides _skipped_parameters metadata
    - Intelligently detects offline devices
    """
    config_repo = ConfigRepository()
    modbus_repo = ModbusRepository()

    # Track devices known to be offline
    offline_devices: Set[str] = set()

    # Concurrently read all devices
    tasks = [
        _read_single_device(
            device_id=device_id,
            parameters=request.parameters,
            service=service,
            config_repo=config_repo,
            modbus_repo=modbus_repo,
            offline_devices=offline_devices,
        )
        for device_id in request.device_ids
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Aggregate results
    data = {}
    success_count = 0
    failed_count = 0
    offline_count = 0

    for result in results:
        if isinstance(result, Exception):
            logger.error(f"[BATCH READ] Exception: {result}")
            failed_count += 1
            continue

        device_id, device_data = result
        data[device_id] = device_data

        # Check device status
        if device_data.get("is_offline"):
            offline_count += 1
            failed_count += 1
        else:
            # Check if any parameter read succeeded
            has_valid_data = any(
                not isinstance(v, dict) or v.get("value") is not None
                for k, v in device_data.items()
                if not k.startswith("_") and k != "is_offline"
            )

            if has_valid_data:
                success_count += 1
            else:
                failed_count += 1

    return {
        "status": ResponseStatus.SUCCESS.value if failed_count == 0 else ResponseStatus.PARTIAL_SUCCESS.value,
        "data": data,
        "summary": {
            "total_devices": len(request.device_ids),
            "success_devices": success_count,
            "failed_devices": failed_count,
            "offline_devices": offline_count,
            "requested_parameters": len(request.parameters),
        },
    }


@router.post(
    "/write",
    summary="Batch write same value to devices",
    description="Write the same parameter value to multiple devices; automatically skips devices that don’t support the parameter.",
)
async def batch_write_devices(
    request: BatchWriteRequest, service: ParameterService = Depends(get_parameter_service)
) -> dict[str, Any]:
    """
    Batch write the same parameter to multiple devices.

    Features:
    - Automatically skips devices where the parameter doesn’t exist
    - Automatically skips devices where the parameter is read-only
    - Distinguishes between success / failed / skipped states
    """
    config_repo = ConfigRepository()

    # Concurrently write to all devices
    tasks = [
        _write_single_device(
            device_id=device_id,
            parameter=request.parameter,
            value=request.value,
            force=request.force,
            service=service,
            config_repo=config_repo,
        )
        for device_id in request.device_ids
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Aggregate results
    data = {}
    success_count = 0
    failed_count = 0
    skipped_count = 0
    errors = []

    for result in results:
        if isinstance(result, Exception):
            logger.error(f"[BATCH WRITE] Exception: {result}")
            failed_count += 1
            errors.append(str(result))
            continue

        device_id, write_result = result
        data[device_id] = write_result

        if write_result.get("skipped"):
            skipped_count += 1
        elif write_result.get("success"):
            success_count += 1
        else:
            failed_count += 1
            errors.append(f"{device_id}: {write_result.get('error')}")

    return {
        "status": ResponseStatus.SUCCESS.value if failed_count == 0 else ResponseStatus.PARTIAL_SUCCESS.value,
        "data": data,
        "summary": {
            "total_devices": len(request.device_ids),
            "success_devices": success_count,
            "failed_devices": failed_count,
            "skipped_devices": skipped_count,
            "parameter": request.parameter,
            "value": request.value,
        },
        "errors": errors if errors else None,
    }


@router.post(
    "/write-multiple",
    summary="Batch write different values to devices",
    description="Flexibly write different parameter values to different devices with automatic validation of parameter existence and writability.",
)
async def batch_write_multiple(
    request: BatchWriteMultipleRequest, service: ParameterService = Depends(get_parameter_service)
) -> dict[str, Any]:
    """
    Batch write different parameters to multiple devices.

    Features:
    - Each write operation independently specifies device, parameter, and value
    - Automatically validates parameter availability and writability
    - Pre-filters invalid operations
    """
    config_repo = ConfigRepository()

    # Concurrently execute all write operations
    tasks = [
        _execute_single_write(write_op=write_op, force=request.force, service=service, config_repo=config_repo)
        for write_op in request.writes
    ]
    results = await asyncio.gather(*tasks)

    # Summarize results
    success_count = sum(1 for r in results if r.get("success"))
    skipped_count = sum(1 for r in results if r.get("skipped"))
    failed_count = len(results) - success_count - skipped_count

    return {
        "status": ResponseStatus.SUCCESS.value if failed_count == 0 else ResponseStatus.PARTIAL_SUCCESS.value,
        "results": results,
        "summary": {
            "total_operations": len(request.writes),
            "success_operations": success_count,
            "failed_operations": failed_count,
            "skipped_operations": skipped_count,
        },
    }


@router.post(
    "/validate",
    summary="Batch validate device connectivity",
    description="Quickly check the connection status of multiple devices.",
)
async def batch_validate_devices(request: BatchValidateRequest) -> dict[str, Any]:
    """
    Batch validate device connectivity.

    Features:
    - Tests connectivity only; no parameter access
    - Applicable to all device models
    - Quickly diagnoses connectivity issues
    """
    modbus_repo = ModbusRepository()

    # Concurrently check all devices
    tasks = [_check_device_connection(device_id, modbus_repo) for device_id in request.device_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Aggregate results
    data = {}
    online_count = 0

    for result in results:
        if isinstance(result, Exception):
            logger.error(f"[BATCH VALIDATE] Exception: {result}")
            continue

        device_id, is_connected = result
        data[device_id] = {"status": "online" if is_connected else "offline", "is_connected": is_connected}
        if is_connected:
            online_count += 1

    return {
        "status": ResponseStatus.SUCCESS.value,
        "data": data,
        "summary": {
            "total_devices": len(request.device_ids),
            "online_devices": online_count,
            "offline_devices": len(request.device_ids) - online_count,
        },
    }


@router.post(
    "/read-all",
    summary="Batch read all parameters",
    description="Automatically read all available parameters for each device; suitable for dashboards.",
)
async def batch_read_all_parameters(
    request: BatchReadAllRequest, service: ParameterService = Depends(get_parameter_service)
) -> dict[str, Any]:
    """
    Batch read all parameters.

    Features:
    - No need to specify parameter lists
    - Automatically reads all parameters for each device
    - Suitable for dashboards and full state queries
    """
    config_repo = ConfigRepository()

    # Concurrently read all devices
    tasks = [_read_device_all_parameters(device_id, service, config_repo) for device_id in request.device_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Aggregate results
    data = {}
    success_count = 0
    failed_count = 0

    for result in results:
        if isinstance(result, Exception):
            logger.error(f"[BATCH READ ALL] Exception: {result}")
            failed_count += 1
            continue

        device_id, device_data = result
        data[device_id] = device_data

        # Check for errors
        if "error" in device_data:
            failed_count += 1
        else:
            success_count += 1

    return {
        "status": ResponseStatus.SUCCESS.value if failed_count == 0 else ResponseStatus.PARTIAL_SUCCESS.value,
        "data": data,
        "summary": {
            "total_devices": len(request.device_ids),
            "success_devices": success_count,
            "failed_devices": failed_count,
        },
    }


# ===== Helper Functions =====


async def _read_single_device(
    device_id: str,
    parameters: list[str],
    service: ParameterService,
    config_repo: ConfigRepository,
    modbus_repo: ModbusRepository,
    offline_devices: Set[str],
) -> tuple[str, dict[str, Any]]:
    """
    Read specified parameters from a single device.

    Args:
        device_id: Device identifier
        parameters: list of parameters to read
        service: Parameter service
        config_repo: Configuration repository
        modbus_repo: Modbus repository
        offline_devices: Mutable set of known offline devices

    Returns:
        tuple: (device_id, device_data)
    """
    device_data = {}

    # Quickly skip devices known to be offline
    if device_id in offline_devices:
        logger.info(f"[BATCH READ] Skipping offline device: {device_id}")
        return device_id, {
            "error": "Device is offline or not responding",
            "is_offline": True,
            "_skipped_parameters": parameters,
        }

    # Get device configuration
    device_config = config_repo.get_device_config(device_id)
    if not device_config:
        return device_id, {"error": "Device not found in configuration", "_skipped_parameters": parameters}

    available_params = device_config.get("available_parameters", [])

    # Only read parameters actually supported by the device
    params_to_read = [p for p in parameters if p in available_params]
    skipped_params = [p for p in parameters if p not in available_params]

    if not params_to_read:
        logger.warning(f"[BATCH READ] Device {device_id}: no requested parameters available")
        return device_id, {
            "error": "None of the requested parameters exist on this device",
            "available_parameters": available_params,
            "_skipped_parameters": skipped_params,
        }

    logger.info(f"[BATCH READ] Device {device_id}: reading {len(params_to_read)}/{len(parameters)} parameters")

    # Read parameters and detect connectivity status
    for i, param in enumerate(params_to_read):
        param_value = await service.read_parameter(device_id, param)

        if param_value.is_valid:
            device_data[param_value.name] = param_value.value
        else:
            # If the first parameter read fails, the device may be offline
            if i == 0 and "Failed to read from Modbus" in (param_value.error_message or ""):
                logger.warning(f"[BATCH READ] First parameter read failed for {device_id}, checking connectivity...")

                # Quick connectivity test
                is_online = await modbus_repo.test_connection(device_id)

                if not is_online:
                    logger.error(f"[BATCH READ] Device {device_id} is offline, skipping remaining parameters")
                    offline_devices.add(device_id)

                    device_data[param] = {"error": "Device offline", "value": None}

                    # Mark remaining parameters as skipped
                    for remaining_param in params_to_read[i + 1 :]:
                        device_data[remaining_param] = {"error": "Skipped (device offline)", "value": None}

                    device_data["is_offline"] = True
                    break

            device_data[param_value.name] = {"error": param_value.error_message, "value": None}

    # Mark which parameters were skipped
    if skipped_params:
        device_data["_skipped_parameters"] = skipped_params

    return device_id, device_data


async def _write_single_device(
    device_id: str, parameter: str, value: float, force: bool, service: ParameterService, config_repo: ConfigRepository
) -> tuple[str, dict[str, Any]]:
    """
    Write a parameter to a single device.

    Args:
        device_id: Device identifier
        parameter: Parameter name
        value: Value to write
        force: Whether to force the write
        service: Parameter service
        config_repo: Configuration repository

    Returns:
        tuple: (device_id, result)
    """
    # Check if the device exists
    device_config = config_repo.get_device_config(device_id)
    if not device_config:
        return device_id, {"success": False, "skipped": True, "error": "Device not found"}

    available_params = device_config.get("available_parameters", [])

    # Check if the parameter exists
    if parameter not in available_params:
        return device_id, {
            "success": False,
            "skipped": True,
            "error": f"Parameter '{parameter}' not available on this device",
            "available_parameters": available_params,
        }

    # Check if the parameter is writable
    param_def = config_repo.get_parameter_definition(device_id, parameter)
    if param_def and not param_def.get("writable", False):
        return device_id, {
            "success": False,
            "skipped": True,
            "error": f"Parameter '{parameter}' is read-only on this device",
        }

    # Perform the write
    result = await service.write_parameter(device_id=device_id, parameter=parameter, value=value, force=force)

    return device_id, result


async def _execute_single_write(
    write_op: dict[str, Any], force: bool, service: ParameterService, config_repo: ConfigRepository
) -> dict[str, Any]:
    """
    Execute a single write operation.

    Args:
        write_op: Write operation definition {"device_id": ..., "parameter": ..., "value": ...}
        force: Whether to force the write
        service: Parameter service
        config_repo: Configuration repository

    Returns:
        dict: Write result
    """
    try:
        device_id = write_op["device_id"]
        parameter = write_op["parameter"]
        value = write_op["value"]

        # Pre-validate: device exists
        device_config = config_repo.get_device_config(device_id)
        if not device_config:
            return {
                "device_id": device_id,
                "parameter": parameter,
                "success": False,
                "skipped": True,
                "error": "Device not found",
            }

        available_params = device_config.get("available_parameters", [])

        # Pre-validate: parameter exists
        if parameter not in available_params:
            return {
                "device_id": device_id,
                "parameter": parameter,
                "success": False,
                "skipped": True,
                "error": f"Parameter '{parameter}' not available on this device",
                "available_parameters": available_params,
            }

        # Pre-validate: parameter is writable
        param_def = config_repo.get_parameter_definition(device_id, parameter)
        if param_def and not param_def.get("writable", False):
            return {
                "device_id": device_id,
                "parameter": parameter,
                "success": False,
                "skipped": True,
                "error": f"Parameter '{parameter}' is read-only on this device",
            }

        # Execute the write
        result = await service.write_parameter(device_id=device_id, parameter=parameter, value=value, force=force)

        return {"device_id": device_id, "parameter": parameter, "value": value, **result}

    except Exception as e:
        logger.error(f"[BATCH WRITE MULTIPLE] Exception: {e}")
        return {
            "device_id": write_op.get("device_id", "unknown"),
            "parameter": write_op.get("parameter", "unknown"),
            "success": False,
            "error": str(e),
        }


async def _check_device_connection(device_id: str, modbus_repo: ModbusRepository) -> tuple[str, bool]:
    """
    Check the connection status of a single device.

    Args:
        device_id: Device identifier
        modbus_repo: Modbus repository

    Returns:
        tuple: (device_id, is_connected)
    """
    is_connected = await modbus_repo.test_connection(device_id, use_cache=False)
    return device_id, is_connected


async def _read_device_all_parameters(
    device_id: str, service: ParameterService, config_repo: ConfigRepository
) -> tuple[str, dict[str, Any]]:
    """
    Read all parameters from a single device.

    Args:
        device_id: Device identifier
        service: Parameter service
        config_repo: Configuration repository

    Returns:
        tuple: (device_id, device_data)
    """
    device_config = config_repo.get_device_config(device_id)
    if not device_config:
        return device_id, {"error": "Device not found"}

    # Get all parameters for the device
    all_params = device_config.get("available_parameters", [])

    logger.info(f"[BATCH READ ALL] Device {device_id}: reading {len(all_params)} parameters")

    device_data = {"model": device_config.get("model"), "type": device_config.get("type"), "parameters": {}}

    # Read all parameters
    param_values = await service.read_multiple_parameters(device_id, all_params)

    success_count = 0
    for param_value in param_values:
        if param_value.is_valid:
            device_data["parameters"][param_value.name] = param_value.value
            success_count += 1
        else:
            device_data["parameters"][param_value.name] = {"error": param_value.error_message, "value": None}

    device_data["_stats"] = {
        "total_parameters": len(all_params),
        "success_parameters": success_count,
        "failed_parameters": len(all_params) - success_count,
    }

    return device_id, device_data
