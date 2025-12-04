"""
WebSocket monitoring router

Demonstrates the ultimate simplification using WebSocketDeviceSession.
Single-device endpoint reduced from ~200 lines to ~40 lines.
"""

import logging

from fastapi import APIRouter, Query, WebSocket

from api.repository.config_repository import ConfigRepository
from api.service.parameter_service import ParameterService
from api.util.connect_manager import ConnectionManager
from api.websocket.message_builder import MessageBuilder
from api.websocket.monitoring_config import MonitoringConfig
from api.websocket.monitoring_handler import MultiDeviceMonitoringHandler
from api.websocket.parameter_paser import ParameterParseError, parse_device_list, parse_multi_device_parameters
from api.websocket.session import WebSocketDeviceSession, WebSocketSessionFactory

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

    All complexity abstracted into:
    - WebSocketDeviceSession: Complete session lifecycle
    - MonitoringTaskHandler: Monitoring loop with failure tracking
    - ControlCommandHandler: Command processing
    - DeviceConnectionTester: Connection validation
    - Parameter parsers: Parameter resolution
    - MessageBuilder: Message construction
    - MonitoringConfig: Configuration management

    This endpoint is now just a thin wrapper that:
    1. Gets dependencies
    2. Creates session
    3. Runs session
    """
    # Get dependencies
    config_repo = ConfigRepository()
    async_device_manager = getattr(websocket.app.state, "async_device_manager", None)

    if async_device_manager is None:
        await websocket.send_json(MessageBuilder.service_unavailable())
        await websocket.close(code=1011)
        return

    service = ParameterService(async_device_manager, config_repo)

    # Create and run session
    session = WebSocketDeviceSession(
        websocket=websocket,
        device_id=device_id,
        service=service,
        config_repo=config_repo,
        manager=manager,
        monitoring_config=monitoring_config,
    )

    await session.run(parameters=parameters, interval=interval)


@router.websocket("/device/{device_id}/v2")
async def monitor_single_device_v2(
    websocket: WebSocket,
    device_id: str,
    parameters: str | None = Query(None),
    interval: float = Query(
        monitoring_config.default_single_device_interval,
        ge=monitoring_config.min_interval,
        le=monitoring_config.max_interval,
    ),
):
    """
    Alternative implementation using WebSocketSessionFactory.

    Even more concise - just 3 lines of business logic!
    """
    config_repo = ConfigRepository()
    async_device_manager = getattr(websocket.app.state, "async_device_manager", None)

    if async_device_manager is None:
        await websocket.send_json(MessageBuilder.service_unavailable())
        await websocket.close(code=1011)
        return

    service = ParameterService(async_device_manager, config_repo)

    # Create factory with shared dependencies
    factory = WebSocketSessionFactory(
        service=service,
        config_repo=config_repo,
        manager=manager,
        monitoring_config=monitoring_config,
    )

    # Run session - that's it!
    await factory.run_session(websocket, device_id, parameters, interval)


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
    """
    await manager.connect(websocket)

    await websocket.send_json(
        MessageBuilder.connection_status(status="connecting", message="Connecting multiple devices...")
    )

    try:
        # Parse device list
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

    # Parse parameters for all devices
    device_params = parse_multi_device_parameters(device_list, parameters, config_repo)

    try:
        # Send connection established
        await websocket.send_json(
            MessageBuilder.connection_status(
                status="connected",
                message="Multiple devices are connected.",
                device_ids=device_list,
                parameters=[p.strip() for p in parameters.split(",")] if parameters else None,
                interval=interval,
            )
        )

        # Use MultiDeviceMonitoringHandler
        handler = MultiDeviceMonitoringHandler(service, manager)
        await handler.start_monitoring(websocket, device_params, interval)

    finally:
        manager.disconnect(websocket)
