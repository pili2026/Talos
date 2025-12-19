"""
WebSocket monitoring router

Demonstrates the ultimate simplification using WebSocketDeviceSession.
Single-device endpoint reduced from ~200 lines to ~40 lines.
"""

import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from api.repository.config_repository import ConfigRepository
from api.service.parameter_service import ParameterService
from api.util.connect_manager import ConnectionManager
from api.websocket.message_builder import MessageBuilder
from api.websocket.monitoring_config import MonitoringConfig
from api.websocket.monitoring_handler import MultiDeviceMonitoringHandler
from api.websocket.parameter_paser import ParameterParseError, parse_device_list, parse_multi_device_parameters
from api.websocket.session import WebSocketDeviceSession
from api.websocket.subscription_session import SubscriptionSession

router = APIRouter()
logger = logging.getLogger(__name__)

# Configuration
monitoring_config = MonitoringConfig()

# Connection manager
manager = ConnectionManager()

# WebSocket close code for service unavailable
WS_UNAVAILABLE = 1013  # Try Again Later


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
    Direct device monitoring (has RTU conflicts).
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

    # ========== Modified: Use TalosAppState API ==========
    try:
        async_device_manager = websocket.app.state.talos.get_device_manager()
        health_manager = websocket.app.state.talos.health_manager
    except Exception as e:
        # CRITICAL: Must accept WebSocket before sending any messages
        await websocket.accept()
        await websocket.send_json(MessageBuilder.service_unavailable())
        await websocket.close(code=1011)
        logger.error(f"Failed to get device manager: {e}")
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
        health_manager=health_manager,
    )

    await session.run(parameters=parameters, interval=interval)


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
    Direct device monitoring (has RTU conflicts).
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

    # ========== Modified: Use TalosAppState API ==========
    try:
        async_device_manager = websocket.app.state.talos.get_device_manager()
    except Exception as e:
        await websocket.send_json(MessageBuilder.service_unavailable())
        await websocket.close(code=1011)
        logger.error(f"Failed to get device manager: {e}")
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


@router.websocket("/subscribe/device/{device_id}")
async def subscribe_single_device(
    websocket: WebSocket,
    device_id: str,
):
    """
    Full-duplex: Subscribe to device + Control commands.

    Zero RTU conflict (reads from PubSub).
    Unified mode only.
    """
    talos = websocket.app.state.talos

    # Standalone API mode: PubSub not available → reject gracefully
    if talos.is_standalone_mode():
        await websocket.accept()
        await websocket.close(
            code=WS_UNAVAILABLE,
            reason="Subscription requires unified mode (Core + API). Start via main_service.py.",
        )
        logger.info(f"[WebSocket] Subscribe rejected (standalone mode): device_id={device_id}")
        return

    try:
        logger.info(f"[WebSocket] Subscribe endpoint called: device_id={device_id}")

        pubsub = talos.get_pubsub()
        async_device_manager = talos.get_device_manager()
        config_repo = ConfigRepository()

        parameter_service = ParameterService(async_device_manager, config_repo)

        session = SubscriptionSession(
            websocket=websocket,
            pubsub=pubsub,
            parameter_service=parameter_service,
            device_filter=device_id,
        )

        await session.run()

    except WebSocketDisconnect:
        # Normal disconnect by client; do not treat as error
        logger.info(f"[WebSocket] Subscribe disconnected: device_id={device_id}")
    except Exception as e:
        logger.error(f"Subscription failed for {device_id}: {e}", exc_info=True)
        # Best-effort close if still connected
        try:
            await websocket.close(code=1011)
        except Exception:
            pass


@router.websocket("/subscribe/dashboard")
async def subscribe_all_devices(websocket: WebSocket):
    talos = websocket.app.state.talos

    if talos.is_standalone_mode():
        await websocket.accept()
        await websocket.close(
            code=WS_UNAVAILABLE,
            reason="Dashboard subscription requires unified mode (Core + API).",
        )
        logger.info("[WebSocket] Dashboard subscribe rejected (standalone mode)")
        return

    pubsub = talos.get_pubsub()
    session = SubscriptionSession(
        websocket=websocket,
        pubsub=pubsub,
        parameter_service=None,
        device_filter=None,
    )
    await session.run()
