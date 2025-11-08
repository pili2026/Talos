"""
Real-time monitoring router providing WebSocket endpoints.
Supports both single-device and multi-device monitoring.
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, Response

from api.repository.config_repository import ConfigRepository
from api.service.parameter_service import ParameterService
from api.util.connect_manager import ConnectionManager


router = APIRouter()
logger = logging.getLogger(__name__)


# ===== ConnectionManager =====

manager = ConnectionManager()


# ===== Helper Functions =====


def get_asyncapi_path() -> Path | None:
    """Get the absolute path to the asyncapi file."""
    current_file = Path(__file__)
    project_root = current_file.parent.parent.parent.parent

    # Try both .yml and .yaml
    for ext in [".yml", ".yaml"]:
        path = project_root / "doc" / f"asyncapi{ext}"
        if path.exists():
            logger.info(f" Found asyncapi file at: {path}")
            return path

    logger.error(" asyncapi file not found")
    return None


# ===== HTTP Endpoints =====


@router.get(
    "/status",
    summary="Monitoring service status",
    description="View the number of active WebSocket connections.",
    tags=["Monitoring"],
)
async def get_monitoring_status():
    """
    Get current monitoring service status.

    Returns:
        dict: Service status information
    """
    return {
        "status": "running",
        "active_connections": len(manager.active_connections),
        "websocket_endpoints": {
            "single_device": "/api/monitoring/device/{deviceId}",
            "multiple_devices": "/api/monitoring/devices",
        },
        "documentation": {
            "rest_api": "/docs",
            "asyncapi_spec": "/api/monitoring/asyncapi.yaml",
            "asyncapi_json": "/api/monitoring/asyncapi.json",
            "asyncapi_docs": "/api/monitoring/doc",
        },
    }


@router.get(
    "/devices",
    summary="List monitorable devices",
    description="Get all devices that can be used for monitoring.",
    tags=["Monitoring"],
)
async def get_available_devices():
    """Get the list of devices available for monitoring."""
    config_repo = ConfigRepository()
    devices = config_repo.get_all_device_configs()

    device_list = []
    for device_id, config in devices.items():
        device_list.append(
            {
                "device_id": device_id,
                "model": config.get("model"),
                "type": config.get("type"),
                "slave_id": config.get("slave_id"),
                "available_parameters": config.get("available_parameters", []),
                "websocket_url": f"/api/monitoring/device/{device_id}",
            }
        )

    return {"total_devices": len(device_list), "devices": device_list}


@router.get(
    "/asyncapi.yaml",
    summary="AsyncAPI specification",
    description="Fetch the AsyncAPI specification for the WebSocket API.",
    tags=["Monitoring"],
)
async def get_asyncapi_spec():
    """Serve the AsyncAPI 3.0.0 specification (YAML)."""
    asyncapi_path = get_asyncapi_path()

    if not asyncapi_path or not asyncapi_path.exists():
        return Response(
            content="AsyncAPI specification not found. Please ensure doc/asyncapi.yml exists.",
            status_code=404,
            media_type="text/plain",
        )

    return FileResponse(path=asyncapi_path, media_type="application/x-yaml", filename="asyncapi.yaml")


@router.get(
    "/asyncapi.json",
    summary="AsyncAPI specification (JSON)",
    description="Fetch the AsyncAPI specification for the WebSocket API (JSON format).",
    tags=["Monitoring"],
)
async def get_asyncapi_spec_json():
    """Serve the AsyncAPI 3.0.0 specification (JSON)."""
    asyncapi_path = get_asyncapi_path()

    if not asyncapi_path or not asyncapi_path.exists():
        return {"error": "AsyncAPI specification not found", "path": str(asyncapi_path) if asyncapi_path else "unknown"}

    try:
        with open(asyncapi_path, "r", encoding="utf-8") as f:
            spec = yaml.safe_load(f)

        if not spec or "asyncapi" not in spec:
            return {"error": "Invalid AsyncAPI document: missing 'asyncapi' field", "file_path": str(asyncapi_path)}

        return spec

    except yaml.YAMLError as e:
        return {"error": f"YAML parsing error: {str(e)}", "file_path": str(asyncapi_path)}
    except Exception as e:
        return {"error": str(e), "file_path": str(asyncapi_path)}


@router.get(
    "/doc",
    summary="AsyncAPI documentation",
    description="View documentation for the WebSocket API (AsyncAPI 3.0.0 download page).",
    tags=["Monitoring"],
)
async def get_asyncapi_docs():
    """Serve a simple documentation page with links to the AsyncAPI spec."""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>WebSocket API Documentation</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                max-width: 900px;
                margin: 50px auto;
                padding: 20px;
                background: #f5f5f5;
            }
            .card {
                background: white;
                border-radius: 8px;
                padding: 30px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            }
            h1 { color: #333; margin-top: 0; }
            h2 { color: #666; border-bottom: 2px solid #667eea; padding-bottom: 10px; }
            .button {
                display: inline-block;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 12px 24px;
                border-radius: 6px;
                text-decoration: none;
                margin: 10px 10px 10px 0;
                transition: transform 0.2s;
            }
            .button:hover { transform: translateY(-2px); }
            .info {
                background: #e3f2fd;
                padding: 15px;
                border-radius: 6px;
                margin: 20px 0;
                border-left: 4px solid #2196f3;
            }
            .warning {
                background: #fff3cd;
                padding: 15px;
                border-radius: 6px;
                margin: 20px 0;
                border-left: 4px solid #ffc107;
            }
            code {
                background: #f5f5f5;
                padding: 3px 8px;
                border-radius: 4px;
                font-family: 'Courier New', monospace;
                color: #c7254e;
            }
            .endpoint {
                background: #f8f9fa;
                padding: 15px;
                border-radius: 6px;
                margin: 10px 0;
                border-left: 3px solid #667eea;
            }
            .endpoint-title {
                font-weight: bold;
                color: #667eea;
                margin-bottom: 5px;
            }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>WebSocket API Documentation</h1>
            
            <div class="info">
                <strong> AsyncAPI Version:</strong> 3.0.0<br>
                <strong> Base URL:</strong> <code>ws://192.168.213.197:8000</code>
            </div>
            
            <div class="warning">
                <strong> Note:</strong> AsyncAPI 3.0.0 is not yet supported by most web rendering tools. 
                Please use one of the options below to view the specification.
            </div>
            
            <h2> View Documentation</h2>
            
            <a href="https://studio.asyncapi.com/?url=http://192.168.213.197:8000/api/monitoring/asyncapi.yaml" 
               class="button" target="_blank">
               Open in AsyncAPI Studio
            </a>
            
            <a href="/api/monitoring/asyncapi.yaml" class="button" download>
                Download YAML
            </a>
            
            <a href="/api/monitoring/asyncapi.json" class="button" target="_blank">
                View JSON
            </a>
            
            <h2>WebSocket Endpoints</h2>
            
            <div class="endpoint">
                <div class="endpoint-title">Single Device Monitoring</div>
                <code>ws://192.168.213.197:8000/api/monitoring/device/{deviceId}</code>
                <p><strong>Query Parameters:</strong></p>
                <ul>
                    <li><code>parameters</code> (optional) - Comma-separated parameter names</li>
                    <li><code>interval</code> (optional) - Update interval in seconds (0.5-60.0, default: 1.0)</li>
                </ul>
                <p><strong>Example:</strong></p>
                <code>ws://192.168.213.197:8000/api/monitoring/device/IMA_C_5?interval=1.0</code>
            </div>
            
            <div class="endpoint">
                <div class="endpoint-title">Multiple Devices Monitoring</div>
                <code>ws://192.168.213.197:8000/api/monitoring/devices</code>
                <p><strong>Query Parameters:</strong></p>
                <ul>
                    <li><code>device_ids</code> (required) - Comma-separated device IDs</li>
                    <li><code>parameters</code> (optional) - Comma-separated parameter names</li>
                    <li><code>interval</code> (optional) - Update interval in seconds (0.5-60.0, default: 2.0)</li>
                </ul>
                <p><strong>Example:</strong></p>
                <code>ws://192.168.213.197:8000/api/monitoring/devices?device_ids=IMA_C_5,SD400_3&interval=2.0</code>
            </div>
            
            <h2>Quick Test</h2>
            <p>Open browser console (F12) and run:</p>
            <pre style="background:#2d2d2d;color:#d4d4d4;padding:15px;border-radius:6px;overflow-x:auto;"><code>const ws = new WebSocket('ws://192.168.213.197:8000/api/monitoring/device/IMA_C_5?interval=1.0');
ws.onmessage = (e) => console.log(JSON.parse(e.data));
ws.onopen = () => console.log(' Connected');
ws.onerror = (e) => console.error(' Error:', e);</code></pre>
            
            <h2>Additional Resources</h2>
            <ul>
                <li><a href="/docs" target="_blank">REST API Documentation (Swagger UI)</a></li>
                <li><a href="/api/monitoring/status" target="_blank">Monitoring Service Status</a></li>
                <li><a href="/api/monitoring/devices" target="_blank">Available Devices</a></li>
            </ul>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


# ===== WebSocket Endpoints =====


@router.websocket("/device/{device_id}")
async def monitor_single_device(
    websocket: WebSocket,
    device_id: str,
    parameters: str | None = Query(None, description="Comma-separated parameter names"),
    interval: float = Query(1.0, ge=0.5, le=60.0, description="Update interval in seconds"),
):
    """
    Monitor and control a single device via WebSocket.

    Supports:
    - Real-time data streaming (server -> client)
    - Device control commands (client -> server)

    Control Message Format:
    {
        "action": "write",
        "parameter": "DOut01",
        "value": 1,
        "force": false  // optional
    }
    """
    await manager.connect(websocket)

    config_repo = ConfigRepository()
    async_device_manager = getattr(websocket.app.state, "async_device_manager", None)
    if async_device_manager is None:
        await websocket.send_json({"type": "error", "message": "AsyncDeviceManager is not available"})
        await websocket.close(code=1011)
        return

    service = ParameterService(async_device_manager, config_repo)

    # Parse the list of parameters to monitor
    if parameters:
        param_list = [p.strip() for p in parameters.split(",")]
    else:
        device_config = config_repo.get_device_config(device_id)
        if not device_config:
            await websocket.send_json({"type": "error", "message": f"Device '{device_id}' not found"})
            await websocket.close()
            return
        param_list = device_config.get("available_parameters", [])

    try:
        # Send connection acknowledgment
        await websocket.send_json(
            {
                "type": "connected",
                "device_id": device_id,
                "parameters": param_list,
                "interval": interval,
                "features": {"monitoring": True, "control": True},
            }
        )

        # Create two concurrent tasks
        async def monitoring_task():
            """Continuous monitoring task."""
            while True:
                try:
                    param_values = await service.read_multiple_parameters(device_id, param_list)

                    data = {}
                    errors = []
                    for param_value in param_values:
                        if param_value.is_valid:
                            data[param_value.name] = {"value": param_value.value, "unit": param_value.unit}
                        else:
                            errors.append(f"{param_value.name}: {param_value.error_message}")

                    message = {
                        "type": "data",
                        "device_id": device_id,
                        "timestamp": datetime.now().isoformat(),
                        "data": data,
                    }

                    if errors:
                        message["errors"] = errors

                    await manager.send_personal_message(message, websocket)
                    await asyncio.sleep(interval)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in monitoring: {e}")
                    await asyncio.sleep(interval)

        async def control_task():
            """Handle control command task."""
            logger.info(f"Control task started for device {device_id}")

            while True:
                try:
                    # Receive client message
                    message = await websocket.receive_json()
                    logger.info(f"[{device_id}] Received: {message}")

                    # Handle write command
                    if message.get("action") == "write":
                        parameter = message.get("parameter", "")
                        value = message.get("value")
                        force = message.get("force", False)

                        if not parameter or value is None:
                            error_msg = "Missing 'parameter' or 'value'"
                            logger.error(f"[{device_id}] {error_msg}")
                            await websocket.send_json({"type": "error", "message": error_msg, "request": message})
                            continue

                        # Execute write
                        try:
                            logger.info(f"[{device_id}] Writing {parameter} = {value} (force={force})")

                            result = await service.write_parameter(
                                device_id=device_id, parameter=parameter, value=value, force=force
                            )

                            logger.info(f"[{device_id}] Write result: {result}")

                            # Send result based on outcome
                            if result.get("success", False):
                                await websocket.send_json(
                                    {
                                        "type": "write_result",
                                        "device_id": device_id,
                                        "parameter": parameter,
                                        "value": value,
                                        "success": True,
                                        "previous_value": result.get("previous_value"),
                                        "new_value": result.get("new_value"),
                                        "was_forced": result.get("was_forced", False),
                                        "message": f"Successfully written {value} to {parameter}",
                                        "timestamp": datetime.now().isoformat(),
                                    }
                                )
                                logger.info(f"[{device_id}]  Write successful")
                            else:
                                error_msg = result.get("error", "Unknown error")
                                await websocket.send_json(
                                    {
                                        "type": "write_result",
                                        "device_id": device_id,
                                        "parameter": parameter,
                                        "value": value,
                                        "success": False,
                                        "error": error_msg,
                                        "timestamp": datetime.now().isoformat(),
                                    }
                                )
                                logger.warning(f"[{device_id}]  Write failed: {error_msg}")

                        except Exception as e:
                            logger.error(f"[{device_id}] Exception in write: {e}", exc_info=True)
                            await websocket.send_json(
                                {
                                    "type": "write_result",
                                    "device_id": device_id,
                                    "parameter": parameter,
                                    "value": value,
                                    "success": False,
                                    "error": str(e),
                                    "timestamp": datetime.now().isoformat(),
                                }
                            )

                    # Handle ping
                    elif message.get("action") == "ping":
                        await websocket.send_json({"type": "pong", "timestamp": datetime.now().isoformat()})

                    else:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "message": f"Unknown action: {message.get('action')}",
                                "supported_actions": ["write", "ping"],
                            }
                        )

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

        # Wait for either task to finish
        done, pending = await asyncio.wait([monitor, control], return_when=asyncio.FIRST_COMPLETED)

        # Cancel any pending tasks
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
    interval: float = Query(2.0, ge=0.5, le=60.0),
):
    """
    Monitor real-time data for multiple devices.

    WebSocket endpoint for streaming data from multiple devices.
    """
    await manager.connect(websocket)

    device_list = [d.strip() for d in device_ids.split(",") if d.strip()]
    if not device_list:
        await websocket.send_json({"type": "error", "message": "No devices specified"})
        await websocket.close()
        return

    config_repo = ConfigRepository()
    async_device_manager = getattr(websocket.app.state, "async_device_manager", None)
    if async_device_manager is None:
        await websocket.send_json({"type": "error", "message": "AsyncDeviceManager is not available"})
        await websocket.close(code=1011)
        return

    service = ParameterService(async_device_manager, config_repo)

    param_list = [p.strip() for p in parameters.split(",")] if parameters else None

    try:
        await websocket.send_json(
            {"type": "connected", "device_ids": device_list, "parameters": param_list, "interval": interval}
        )

        while True:
            try:
                devices_data = {}

                async def read_device(device_id: str):
                    if param_list:
                        params = param_list
                    else:
                        device_config = config_repo.get_device_config(device_id)
                        params = device_config.get("available_parameters", []) if device_config else []

                    param_values = await service.read_multiple_parameters(device_id, params)

                    data = {}
                    for param_value in param_values:
                        if param_value.is_valid:
                            data[param_value.name] = {"value": param_value.value, "unit": param_value.unit}

                    return device_id, data

                tasks = [read_device(device_id) for device_id in device_list]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for result in results:
                    if isinstance(result, Exception):
                        continue
                    device_id, data = result
                    devices_data[device_id] = data

                message = {"type": "data", "timestamp": datetime.now().isoformat(), "devices": devices_data}

                await manager.send_personal_message(message, websocket)
                await asyncio.sleep(interval)

            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await websocket.send_json({"type": "error", "message": str(e)})
                await asyncio.sleep(interval)

    finally:
        manager.disconnect(websocket)
