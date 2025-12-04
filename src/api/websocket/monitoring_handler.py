"""
Monitoring task handler for WebSocket device monitoring.

Manages the continuous monitoring loop with failure tracking and
automatic error recovery, following Talos reliability patterns.
"""

import asyncio
import logging
from typing import Protocol

from fastapi import WebSocket

from api.model.responses import ParameterValue
from api.websocket.config import MonitoringConfig
from api.websocket.message_builder import MessageBuilder

logger = logging.getLogger(__name__)


class ParameterServiceProtocol(Protocol):
    """Protocol for parameter service dependency."""

    async def read_multiple_parameters(self, device_id: str, parameters: list[str]) -> list[ParameterValue]:
        """Read multiple parameters from a device."""
        ...


class ConnectionManagerProtocol(Protocol):
    """Protocol for connection manager dependency."""

    async def send_personal_message(self, message: dict, websocket: WebSocket) -> None:
        """Send message to specific WebSocket."""
        ...


class MonitoringTaskHandler:
    """
    Handles continuous device monitoring with failure tracking.

    Follows Talos principle: Monitor continuously but fail gracefully
    when device becomes unresponsive.

    Example:
        >>> handler = MonitoringTaskHandler(service, monitoring_config)
        >>> await handler.start_monitoring(
        ...     websocket=websocket,
        ...     device_id="VFD_01",
        ...     parameters=["frequency", "current"],
        ...     interval=2.0
        ... )
    """

    def __init__(
        self,
        parameter_service: ParameterServiceProtocol,
        monitoring_config: MonitoringConfig,
        connection_manager: ConnectionManagerProtocol | None = None,
    ):
        """
        Initialize monitoring task handler.

        Args:
            parameter_service: Service for reading parameters
            monitoring_config: Monitoring configuration
            connection_manager: Optional connection manager for broadcasting
        """
        self.service = parameter_service
        self.config = monitoring_config
        self.manager = connection_manager
        self._consecutive_failures = 0
        self._is_running = False

    async def start_monitoring(
        self,
        websocket: WebSocket,
        device_id: str,
        parameters: list[str],
        interval: float,
    ) -> None:
        """
        Start continuous monitoring loop.

        Monitors device parameters and sends updates via WebSocket.
        Automatically tracks failures and closes connection after
        max consecutive failures.

        Args:
            websocket: WebSocket connection
            device_id: Device identifier
            parameters: List of parameters to monitor
            interval: Update interval in seconds

        Side Effects:
            - Sends data updates to websocket
            - Closes websocket on persistent failures
            - Logs monitoring events

        Example:
            >>> handler = MonitoringTaskHandler(service, config)
            >>> await handler.start_monitoring(ws, "VFD_01", ["freq"], 2.0)
        """
        self._consecutive_failures = 0
        self._is_running = True

        logger.info(f"[{device_id}] Starting monitoring loop (interval={interval}s)")

        try:
            while self._is_running:
                try:
                    # Read parameters
                    param_value_list = await self.service.read_multiple_parameters(device_id, parameters)

                    # Check for valid data
                    has_valid_data = any(pv.is_valid for pv in param_value_list)

                    if not has_valid_data:
                        await self._handle_read_failure(device_id)
                        if self._should_disconnect():
                            await self._disconnect_due_to_failures(websocket, device_id)
                            break
                    else:
                        # Reset failure counter on successful read
                        self._consecutive_failures = 0

                        # Process and send data
                        data, errors = self._process_parameter_values(param_value_list)
                        await self._send_data_update(websocket, device_id, data, errors)

                    await asyncio.sleep(interval)

                except asyncio.CancelledError:
                    logger.info(f"[{device_id}] Monitoring task cancelled")
                    break

                except Exception as e:
                    await self._handle_exception(device_id, e)
                    if self._should_disconnect():
                        await self._disconnect_due_to_failures(websocket, device_id)
                        break
                    await asyncio.sleep(interval)

        finally:
            self._is_running = False
            logger.info(f"[{device_id}] Monitoring loop stopped")

    def stop(self) -> None:
        """
        Stop the monitoring loop.

        Sets flag to stop the monitoring loop at next iteration.
        """
        self._is_running = False
        logger.info("Monitoring stop requested")

    @property
    def consecutive_failures(self) -> int:
        """Get current consecutive failure count."""
        return self._consecutive_failures

    @property
    def is_running(self) -> bool:
        """Check if monitoring loop is running."""
        return self._is_running

    def _should_disconnect(self) -> bool:
        """Check if should disconnect due to failures."""
        return self._consecutive_failures >= self.config.max_consecutive_failures

    async def _handle_read_failure(self, device_id: str) -> None:
        """Handle a failed read attempt."""
        self._consecutive_failures += 1
        logger.warning(
            f"[{device_id}] No valid data " f"({self._consecutive_failures}/{self.config.max_consecutive_failures})"
        )

    async def _handle_exception(self, device_id: str, error: Exception) -> None:
        """Handle exception during monitoring."""
        self._consecutive_failures += 1
        logger.error(
            f"[{device_id}] Error in monitoring "
            f"({self._consecutive_failures}/{self.config.max_consecutive_failures}): {error}",
            exc_info=True,
        )

    async def _disconnect_due_to_failures(self, websocket: WebSocket, device_id: str) -> None:
        """Disconnect WebSocket due to too many failures."""
        logger.error(f"[{device_id}] Max consecutive failures reached. Disconnecting.")
        await websocket.send_json(MessageBuilder.connection_lost(device_id))
        await websocket.close(code=1011)

    def _process_parameter_values(self, param_value_list: list[ParameterValue]) -> tuple[dict, list[str] | None]:
        """
        Process parameter values into data dict and errors list.

        Args:
            param_value_list: List of parameter values

        Returns:
            Tuple of (data_dict, errors_list)
        """
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

        return data, errors if errors else None

    async def _send_data_update(
        self,
        websocket: WebSocket,
        device_id: str,
        data: dict,
        errors: list[str] | None,
    ) -> None:
        """Send data update to WebSocket."""
        message = MessageBuilder.data_update(device_id, data, errors)

        if self.manager:
            await self.manager.send_personal_message(message, websocket)
        else:
            await websocket.send_json(message)


class MultiDeviceMonitoringHandler:
    """
    Handles monitoring for multiple devices simultaneously.

    Optimized for monitoring multiple devices with concurrent reads.
    """

    def __init__(
        self,
        parameter_service: ParameterServiceProtocol,
        connection_manager: ConnectionManagerProtocol | None = None,
    ):
        """Initialize multi-device monitoring handler."""
        self.service = parameter_service
        self.manager = connection_manager
        self._is_running = False

    async def start_monitoring(
        self,
        websocket: WebSocket,
        device_params: dict[str, list[str]],
        interval: float,
    ) -> None:
        """
        Start monitoring multiple devices.

        Args:
            websocket: WebSocket connection
            device_params: Dict mapping device_id to parameter list
            interval: Update interval in seconds
        """
        self._is_running = True
        logger.info(f"Starting multi-device monitoring for {len(device_params)} devices")

        try:
            while self._is_running:
                try:
                    devices_data = {}

                    # Read all devices concurrently
                    async def read_device(device_id: str):
                        params = device_params.get(device_id, [])
                        if not params:
                            return device_id, {}

                        param_values = await self.service.read_multiple_parameters(device_id, params)

                        data = {}
                        for param_value in param_values:
                            if param_value.is_valid:
                                data[param_value.name] = {
                                    "value": param_value.value,
                                    "unit": param_value.unit,
                                }

                        return device_id, data

                    tasks = [read_device(device_id) for device_id in device_params.keys()]
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    for result in results:
                        if isinstance(result, Exception):
                            logger.error(f"Error reading device: {result}")
                            continue
                        device_id, data = result
                        devices_data[device_id] = data

                    # Send update
                    message = MessageBuilder.multi_device_data_update(devices_data)
                    if self.manager:
                        await self.manager.send_personal_message(message, websocket)
                    else:
                        await websocket.send_json(message)

                    await asyncio.sleep(interval)

                except asyncio.CancelledError:
                    logger.info("Multi-device monitoring cancelled")
                    break

                except Exception as e:
                    logger.error(f"Error in multi-device monitoring: {e}")
                    await asyncio.sleep(interval)

        finally:
            self._is_running = False
            logger.info("Multi-device monitoring stopped")

    def stop(self) -> None:
        """Stop monitoring."""
        self._is_running = False
