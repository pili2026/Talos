"""
Real-Time Monitoring Router

Provides WebSocket endpoints for real-time device monitoring.
Supports both single-device and multi-device monitoring.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Set
import asyncio

import logging
from datetime import datetime

from api.service.parameter_service import ParameterService
from api.repository.modbus_repository import ModbusRepository
from api.repository.config_repository import ConfigRepository

router = APIRouter()
logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    WebSocket Connection Manager

    Manages multiple WebSocket client connections.
    Supports both broadcasting and unicast communication.
    """

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"New WebSocket connection. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Remove a disconnected client."""
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket disconnected. Total: {len(self.active_connections)}")

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """Send a message to a specific client."""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            self.disconnect(websocket)

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected clients."""
        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting: {e}")
                disconnected.add(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)


manager = ConnectionManager()


@router.websocket("/device/{device_id}")
async def monitor_single_device(
    websocket: WebSocket,
    device_id: str,
    parameters: str | None = Query(None, description="Comma-separated parameter names"),
    interval: float = Query(1.0, ge=0.5, le=60.0, description="Update interval in seconds"),
):
    """
    Monitor real-time data for a single device.

    WebSocket URL:
    ws://localhost:8000/api/monitoring/device/vfd_001?parameters=hz,current&interval=2.0

    Args:
        device_id: Device identifier.
        parameters: Parameters to monitor (comma-separated). If not specified, all parameters will be monitored.
        interval: Update interval in seconds.

    Push format:
    {
        "type": "data",
        "device_id": "vfd_001",
        "timestamp": "2024-01-01T12:00:00",
        "data": {
            "hz": 60.0,
            "current": 10.5
        }
    }
    """
    await manager.connect(websocket)

    # Initialize service instance
    modbus_repo = ModbusRepository()
    config_repo = ConfigRepository()
    service = ParameterService(modbus_repo, config_repo)

    # Parse parameters to monitor
    if parameters:
        param_list = [p.strip().upper() for p in parameters.split(",")]
    else:
        # Retrieve all available parameters for the device
        device_config = config_repo.get_device_config(device_id)
        if not device_config:
            await websocket.send_json({"type": "error", "message": f"Device '{device_id}' not found"})
            await websocket.close()
            return
        param_list = device_config.get("available_parameters", [])

    try:
        # Send initial connection confirmation
        await websocket.send_json(
            {"type": "connected", "device_id": device_id, "parameters": param_list, "interval": interval}
        )

        # Continuously push data
        while True:
            try:
                # Read all parameters
                param_values = await service.read_multiple_parameters(device_id, param_list)

                # Format data
                data = {}
                errors = []
                for param_value in param_values:
                    if param_value.is_valid:
                        data[param_value.name] = {"value": param_value.value, "unit": param_value.unit}
                    else:
                        errors.append(f"{param_value.name}: {param_value.error_message}")

                # Push data
                message = {
                    "type": "data",
                    "device_id": device_id,
                    "timestamp": datetime.now().isoformat(),
                    "data": data,
                }

                if errors:
                    message["errors"] = errors

                await manager.send_personal_message(message, websocket)

                # Wait for the next update
                await asyncio.sleep(interval)

            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await websocket.send_json({"type": "error", "message": str(e)})
                await asyncio.sleep(interval)

    finally:
        manager.disconnect(websocket)


@router.websocket("/devices")
async def monitor_multiple_devices(
    websocket: WebSocket,
    device_ids: str = Query(..., description="Comma-separated device IDs"),
    parameters: str | None = Query(None, description="Comma-separated parameter names"),
    interval: float = Query(2.0, ge=0.5, le=60.0),
):
    """
    Monitor real-time data for multiple devices.

    WebSocket URL:
    ws://localhost:8000/api/monitoring/devices?device_ids=vfd_001,vfd_002&parameters=hz,current&interval=2.0

    Push format:
    {
        "type": "data",
        "timestamp": "2024-01-01T12:00:00",
        "devices": {
            "vfd_001": {"hz": 60.0, "current": 10.5},
            "vfd_002": {"hz": 55.0, "current": 9.8}
        }
    }
    """
    await manager.connect(websocket)

    # Parse device list
    device_list = [d.strip() for d in device_ids.split(",") if d.strip()]
    if not device_list:
        await websocket.send_json({"type": "error", "message": "No devices specified"})
        await websocket.close()
        return

    # Initialize service instance
    modbus_repo = ModbusRepository()
    config_repo = ConfigRepository()
    service = ParameterService(modbus_repo, config_repo)

    # Parse parameter list
    param_list = [p.strip().upper() for p in parameters.split(",")] if parameters else None

    try:
        # Send initial connection confirmation
        await websocket.send_json(
            {"type": "connected", "device_ids": device_list, "parameters": param_list, "interval": interval}
        )

        # Continuously push data
        while True:
            try:
                devices_data = {}

                # Concurrently read all devices
                async def read_device(device_id: str):
                    # Determine which parameters to read
                    if param_list:
                        params = param_list
                    else:
                        device_config = config_repo.get_device_config(device_id)
                        params = device_config.get("available_parameters", []) if device_config else []

                    # Read parameters
                    param_values = await service.read_multiple_parameters(device_id, params)

                    # Format data
                    data = {}
                    for param_value in param_values:
                        if param_value.is_valid:
                            data[param_value.name] = {"value": param_value.value, "unit": param_value.unit}

                    return device_id, data

                # Concurrent execution
                tasks = [read_device(device_id) for device_id in device_list]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Process results
                for result in results:
                    if isinstance(result, Exception):
                        continue
                    device_id, data = result
                    devices_data[device_id] = data

                # Push data
                message = {"type": "data", "timestamp": datetime.now().isoformat(), "devices": devices_data}

                await manager.send_personal_message(message, websocket)

                # Wait for the next update
                await asyncio.sleep(interval)

            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await websocket.send_json({"type": "error", "message": str(e)})
                await asyncio.sleep(interval)

    finally:
        manager.disconnect(websocket)


@router.get("/status", summary="Get monitoring status", description="View the number of active WebSocket connections")
async def get_monitoring_status():
    """
    Get the current monitoring service status.

    Returns:
        dict: Monitoring status information.
    """
    return {"active_connections": len(manager.active_connections), "status": "running"}
