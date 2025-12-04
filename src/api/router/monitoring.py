"""
WebSocket monitoring router - Stage 2 Refactored Version

Demonstrates usage of DeviceConnectionTester and parameter parsing utilities.
Significantly simplified compared to original implementation.
"""

import asyncio
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from api.model.responses import ParameterValue
from api.repository.config_repository import ConfigRepository
from api.service.parameter_service import ParameterService
from api.util.connect_manager import ConnectionManager
from api.websocket.config import MonitoringConfig
from api.websocket.connection_tester import DeviceConnectionTester
from api.websocket.message_builder import MessageBuilder
from api.websocket.parameter_paser import (
    ParameterParseError,
    parse_device_list,
    parse_multi_device_parameters,
    parse_parameter_list,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Configuration
monitoring_config = MonitoringConfig()

# Connection manager
manager = ConnectionManager()


# ===== WebSocket Endpoints =====


@router.websocket("/device/{device_id}")
async def monitor_single_device(
    websocket: WebSocket,
    device_id: str,
    parameters: str | None = Query(None, description="Comma-separated parameter names"),
    interval: float = Query(
        monitoring_config.default_single_device_interval,
        ge=monitoring_config.min_interval,
        le=monitoring_config.max_interval,
        description="Update interval in seconds",
    ),
):
    """
    Monitor and control a single device via WebSocket.

    Stage 2: Using DeviceConnectionTester and parameter parsing utilities.

    Reduced from ~200 lines to ~100 lines through:
    - DeviceConnectionTester handles all connection testing and error notification
    - parse_parameter_list handles parameter resolution
    - MessageBuilder handles all message construction
    """
    await manager.connect(websocket)

    config_repo = ConfigRepository()
    async_device_manager = getattr(websocket.app.state, "async_device_manager", None)

    if async_device_manager is None:
        await websocket.send_json(MessageBuilder.service_unavailable())
        await websocket.close(code=1011)
        return

    service = ParameterService(async_device_manager, config_repo)

    try:
        # Parse parameters - handles both specified and default cases
        # Replaces ~15 lines of parameter parsing logic
        param_list = parse_parameter_list(parameters, device_id, config_repo)

    except ParameterParseError as e:
        # Automatically sends appropriate error message
        if "not found" in str(e):
            await websocket.send_json(MessageBuilder.device_not_found(device_id))
        else:
            await websocket.send_json(MessageBuilder.no_parameters_available(device_id))
        await websocket.close()
        return

    # Test connection - handles all testing logic and error notification
    # Replaces ~30 lines of connection testing code
    tester = DeviceConnectionTester(service)
    if not await tester.test_and_notify(websocket, device_id, param_list):
        await websocket.close(code=1011)
        return

    try:
        # Send connection acknowledgment
        await websocket.send_json(
            MessageBuilder.connection_established(
                device_id=device_id,
                parameters=param_list,
                interval=interval,
                support_control=monitoring_config.enable_control_commands,
            )
        )

        consecutive_failures = 0

        # Monitoring task
        async def monitoring_task():
            nonlocal consecutive_failures

            while True:
                try:
                    param_value_list: list[ParameterValue] = await service.read_multiple_parameters(
                        device_id, param_list
                    )

                    has_valid_data = any(pv.is_valid for pv in param_value_list)

                    if not has_valid_data:
                        consecutive_failures += 1
                        logger.warning(
                            f"[{device_id}] No valid data "
                            f"({consecutive_failures}/{monitoring_config.max_consecutive_failures})"
                        )

                        if consecutive_failures >= monitoring_config.max_consecutive_failures:
                            await websocket.send_json(MessageBuilder.connection_lost(device_id))
                            await websocket.close(code=1011)
                            break
                    else:
                        consecutive_failures = 0

                    # Process parameter values
                    data = {}
                    errors = []
                    for param_value in param_value_list:
                        if param_value.is_valid:
                            data[param_value.name] = {
                                "value": param_value.value,
                                "unit": param_value.unit,
                            }
                        else:
                            errors.append(f"{param_value.name}: {param_value.error_message}")

                    # Send data update - single line with MessageBuilder
                    await manager.send_personal_message(
                        MessageBuilder.data_update(device_id, data, errors if errors else None),
                        websocket,
                    )
                    await asyncio.sleep(interval)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    consecutive_failures += 1
                    logger.error(
                        f"[{device_id}] Error in monitoring "
                        f"({consecutive_failures}/{monitoring_config.max_consecutive_failures}): {e}"
                    )

                    if consecutive_failures >= monitoring_config.max_consecutive_failures:
                        await websocket.send_json(MessageBuilder.too_many_errors())
                        await websocket.close(code=1011)
                        break

                    await asyncio.sleep(interval)

        # Control task
        async def control_task():
            logger.info(f"Control task started for device {device_id}")

            while True:
                try:
                    message = await websocket.receive_json()
                    logger.info(f"[{device_id}] Received: {message}")

                    if message.get("action") == "write":
                        parameter = message.get("parameter", "")
                        value = message.get("value")
                        force = message.get("force", False)

                        if not parameter or value is None:
                            await websocket.send_json(MessageBuilder.invalid_write_request(message))
                            continue

                        try:
                            logger.info(f"[{device_id}] Writing {parameter} = {value} (force={force})")

                            result = await service.write_parameter(
                                device_id=device_id, parameter=parameter, value=value, force=force
                            )

                            # Use MessageBuilder for write results - replaces ~20 lines
                            if result.get("success", False):
                                response = MessageBuilder.write_success(
                                    device_id=device_id,
                                    parameter=parameter,
                                    value=value,
                                    previous_value=result.get("previous_value"),
                                    new_value=result.get("new_value"),
                                    was_forced=result.get("was_forced", False),
                                )
                            else:
                                response = MessageBuilder.write_failure(
                                    device_id=device_id,
                                    parameter=parameter,
                                    value=value,
                                    error=result.get("error", "Unknown error"),
                                )

                            await websocket.send_json(response)

                        except Exception as e:
                            logger.error(f"[{device_id}] Exception in write: {e}", exc_info=True)
                            await websocket.send_json(
                                MessageBuilder.write_failure(
                                    device_id=device_id, parameter=parameter, value=value, error=str(e)
                                )
                            )

                    elif message.get("action") == "ping":
                        await websocket.send_json(MessageBuilder.pong())

                    else:
                        await websocket.send_json(MessageBuilder.unknown_action(message.get("action")))

                except asyncio.CancelledError:
                    logger.info(f"[{device_id}] Control task cancelled")
                    break
                except WebSocketDisconnect:
                    logger.info(f"[{device_id}] WebSocket disconnected")
                    break
                except Exception as e:
                    logger.error(f"[{device_id}] Error in control task: {e}", exc_info=True)

        # Run both tasks concurrently
        monitor = asyncio.create_task(monitoring_task())
        control = asyncio.create_task(control_task())

        done, pending = await asyncio.wait([monitor, control], return_when=asyncio.FIRST_COMPLETED)

        for task in pending:
            task.cancel()

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for device {device_id}")
    except Exception as e:
        logger.error(f"Error in WebSocket for device {device_id}: {e}", exc_info=True)
    finally:
        manager.disconnect(websocket)


@router.websocket("/devices")
async def monitor_multiple_devices(
    websocket: WebSocket,
    device_ids: str = Query(..., description="Comma-separated device IDs"),
    parameters: str | None = Query(None, description="Comma-separated parameter names"),
    interval: float = Query(
        monitoring_config.default_multi_device_interval,
        ge=monitoring_config.min_interval,
        le=monitoring_config.max_interval,
    ),
):
    """
    Monitor real-time data for multiple devices.

    Stage 2: Using parse_device_list and parse_multi_device_parameters.

    Simplified device and parameter parsing.
    """
    await manager.connect(websocket)

    try:
        # Parse device list - replaces ~5 lines
        device_list = parse_device_list(device_ids)
    except ParameterParseError:
        await websocket.send_json(MessageBuilder.no_devices_specified())
        await websocket.close()
        return

    config_repo = ConfigRepository()
    async_device_manager = getattr(websocket.app.state, "async_device_manager", None)

    if async_device_manager is None:
        await websocket.send_json(MessageBuilder.service_unavailable())
        await websocket.close(code=1011)
        return

    service = ParameterService(async_device_manager, config_repo)

    # Parse parameters for all devices - replaces ~15 lines
    device_params = parse_multi_device_parameters(device_list, parameters, config_repo)

    try:
        await websocket.send_json(
            MessageBuilder.multi_device_connection_established(
                device_ids=device_list,
                parameters=[p.strip() for p in parameters.split(",")] if parameters else None,
                interval=interval,
            )
        )

        while True:
            try:
                devices_data = {}

                async def read_device(device_id: str):
                    params = device_params.get(device_id, [])
                    if not params:
                        return device_id, {}

                    param_values = await service.read_multiple_parameters(device_id, params)

                    data = {}
                    for param_value in param_values:
                        if param_value.is_valid:
                            data[param_value.name] = {
                                "value": param_value.value,
                                "unit": param_value.unit,
                            }

                    return device_id, data

                tasks = [read_device(device_id) for device_id in device_list]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for result in results:
                    if isinstance(result, Exception):
                        continue
                    device_id, data = result
                    devices_data[device_id] = data

                # Use MessageBuilder - single line
                await manager.send_personal_message(MessageBuilder.multi_device_data_update(devices_data), websocket)
                await asyncio.sleep(interval)

            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await websocket.send_json(MessageBuilder.error(str(e)))
                await asyncio.sleep(interval)

    finally:
        manager.disconnect(websocket)
