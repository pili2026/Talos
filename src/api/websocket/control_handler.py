"""
Control command handler for WebSocket device control.

Handles incoming WebSocket control commands (write, ping, etc.)
following Talos command processing patterns.
"""

import asyncio
import logging
from typing import Protocol

from fastapi import WebSocket, WebSocketDisconnect

from api.websocket.message_builder import MessageBuilder

logger = logging.getLogger(__name__)


class ParameterServiceProtocol(Protocol):
    """Protocol for parameter service dependency."""

    async def write_parameter(self, device_id: str, parameter: str, value: float | int, force: bool = False) -> dict:
        """Write parameter to device."""
        ...


class ControlCommandHandler:
    """
    Handles WebSocket control commands for devices.

    Processes incoming commands like write, ping, and provides
    appropriate responses.

    Example:
        >>> handler = ControlCommandHandler(parameter_service)
        >>> await handler.handle_commands(websocket, "VFD_01")
    """

    def __init__(self, parameter_service: ParameterServiceProtocol):
        """
        Initialize control command handler.

        Args:
            parameter_service: Service for writing parameters
        """
        self.service = parameter_service
        self._is_running = False

    async def handle_commands(self, websocket: WebSocket, device_id: str) -> None:
        """
        Process incoming control commands from WebSocket.

        Continuously listens for commands and processes them:
        - write: Write parameter value
        - ping: Respond with pong
        - unknown: Report unknown action

        Args:
            websocket: WebSocket connection
            device_id: Device identifier

        Example:
            >>> handler = ControlCommandHandler(service)
            >>> await handler.handle_commands(websocket, "VFD_01")
        """
        self._is_running = True
        logger.info(f"[{device_id}] Control command handler started")

        try:
            while self._is_running:
                try:
                    message = await websocket.receive_json()
                    logger.info(f"[{device_id}] Received command: {message}")

                    action = message.get("action")

                    if action == "write":
                        await self._handle_write_command(websocket, device_id, message)
                    elif action == "ping":
                        await self._handle_ping_command(websocket)
                    else:
                        await self._handle_unknown_action(websocket, action)

                except asyncio.CancelledError:
                    logger.info(f"[{device_id}] Control handler cancelled")
                    break

                except WebSocketDisconnect:
                    logger.info(f"[{device_id}] WebSocket disconnected")
                    break

                except Exception as e:
                    logger.error(f"[{device_id}] Error processing command: {e}", exc_info=True)
                    await websocket.send_json(MessageBuilder.error(f"Command processing error: {str(e)}"))

        finally:
            self._is_running = False
            logger.info(f"[{device_id}] Control handler stopped")

    def stop(self) -> None:
        """Stop command processing."""
        self._is_running = False

    @property
    def is_running(self) -> bool:
        """Check if handler is running."""
        return self._is_running

    async def _handle_write_command(self, websocket: WebSocket, device_id: str, message: dict) -> None:
        """
        Handle write parameter command.

        Args:
            websocket: WebSocket connection
            device_id: Device identifier
            message: Command message containing parameter, value, force
        """
        parameter = message.get("parameter", "")
        value = message.get("value")
        force = message.get("force", False)

        # Validate command
        if not parameter or value is None:
            await websocket.send_json(MessageBuilder.invalid_write_request(message))
            return

        try:
            logger.info(f"[{device_id}] Writing {parameter} = {value} (force={force})")

            result = await self.service.write_parameter(
                device_id=device_id, parameter=parameter, value=value, force=force
            )

            # Send response
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
            logger.error(f"[{device_id}] Write exception: {e}", exc_info=True)
            await websocket.send_json(
                MessageBuilder.write_failure(
                    device_id=device_id,
                    parameter=parameter,
                    value=value,
                    error=str(e),
                )
            )

    async def _handle_ping_command(self, websocket: WebSocket) -> None:
        """Handle ping command."""
        await websocket.send_json(MessageBuilder.pong())

    async def _handle_unknown_action(self, websocket: WebSocket, action: str | None) -> None:
        """Handle unknown action."""
        await websocket.send_json(MessageBuilder.unknown_action(action))


class WriteCommand:
    """
    Represents a write parameter command.

    Provides a structured representation of write commands.
    """

    def __init__(
        self,
        device_id: str,
        parameter: str,
        value: float | int,
        force: bool = False,
    ):
        self.device_id = device_id
        self.parameter = parameter
        self.value = value
        self.force = force

    @classmethod
    def from_message(cls, device_id: str, message: dict) -> "WriteCommand":
        """
        Create WriteCommand from WebSocket message.

        Args:
            device_id: Device identifier
            message: WebSocket message dict

        Returns:
            WriteCommand instance

        Raises:
            ValueError: If required fields missing
        """
        parameter = message.get("parameter")
        value = message.get("value")

        if not parameter or value is None:
            raise ValueError("Missing required fields: parameter, value")

        return cls(
            device_id=device_id,
            parameter=parameter,
            value=value,
            force=message.get("force", False),
        )

    def __repr__(self) -> str:
        return (
            f"WriteCommand(device={self.device_id}, " f"param={self.parameter}, value={self.value}, force={self.force})"
        )
