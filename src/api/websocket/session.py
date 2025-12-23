"""
WebSocket device session management.

Provides high-level session management for WebSocket device monitoring
and control, integrating all components into a unified interface.
"""

import asyncio
import logging
from typing import Protocol

from fastapi import WebSocket, WebSocketDisconnect

from api.websocket.connection_tester import DeviceConnectionTester
from api.websocket.control_handler import ControlCommandHandler
from api.websocket.message_builder import MessageBuilder
from api.websocket.monitoring_config import MonitoringConfig
from api.websocket.monitoring_handler import MonitoringTaskHandler
from api.websocket.parameter_paser import ParameterParseError, parse_parameter_list
from core.util.device_health_manager import DeviceHealthManager

logger = logging.getLogger(__name__)


class ParameterServiceProtocol(Protocol):
    """Protocol for parameter service dependency."""

    async def read_multiple_parameters(self, device_id: str, parameters: list[str]): ...

    async def write_parameter(self, device_id: str, parameter: str, value: float | int, force: bool = False): ...


class ConfigRepositoryProtocol(Protocol):
    """Protocol for configuration repository dependency."""

    def get_device_config(self, device_id: str) -> dict | None: ...


class ConnectionManagerProtocol(Protocol):
    """Protocol for connection manager dependency."""

    async def connect(self, websocket: WebSocket) -> None: ...

    def disconnect(self, websocket: WebSocket) -> None: ...

    async def send_personal_message(self, message: dict, websocket: WebSocket) -> None: ...


class WebSocketDeviceSession:
    """
    High-level WebSocket session management for device monitoring and control.

    Integrates connection testing, monitoring, and control into a single
    unified interface. Simplifies WebSocket endpoint implementation.

    Example:
        >>> session = WebSocketDeviceSession(
        ...     websocket=websocket,
        ...     device_id="VFD_01",
        ...     service=parameter_service,
        ...     config_repo=config_repository,
        ...     manager=connection_manager,
        ...     monitoring_config=monitoring_config
        ... )
        >>> await session.run(parameters="frequency,current", interval=2.0)
    """

    def __init__(
        self,
        websocket: WebSocket,
        device_id: str,
        service: ParameterServiceProtocol,
        config_repo: ConfigRepositoryProtocol,
        manager: ConnectionManagerProtocol,
        monitoring_config: MonitoringConfig | None = None,
        health_manager: DeviceHealthManager | None = None,
    ):
        """
        Initialize WebSocket device session.

        Args:
            websocket: WebSocket connection
            device_id: Device identifier
            service: Parameter service for reading/writing
            config_repo: Configuration repository
            manager: Connection manager
            monitoring_config: Optional monitoring configuration
        """
        self.websocket = websocket
        self.device_id = device_id
        self.service = service
        self.config_repo = config_repo
        self.manager = manager
        self.monitoring_config = monitoring_config or MonitoringConfig()
        self.health_manager = health_manager

    async def run(self, parameters: str | None = None, interval: float | None = None) -> None:
        """
        Run the complete WebSocket session.
        """
        await self.manager.connect(self.websocket)

        try:
            # Soft gate: do not reject solely by cached health.
            if self.health_manager and not self.health_manager.is_healthy(self.device_id):
                st = self.health_manager.get_status(self.device_id)
                logger.warning(f"[WebSocket] cached unhealthy, will re-test: device_id={self.device_id}, st={st}")

            await self.websocket.send_json(
                MessageBuilder.connection_status(
                    status="connecting",
                    device_id=self.device_id,
                    message="Test device connectivity...",
                )
            )

            param_list: list[str] | None = await self._parse_parameters(parameters)
            if param_list is None:
                return

            tester = DeviceConnectionTester(parameter_service=self.service)
            is_online, error_msg = await tester.test_connection(
                device_id=self.device_id,
                test_parameters=param_list,
            )

            if not is_online:
                await self.websocket.send_json(
                    MessageBuilder.connection_status(
                        status="device_offline",
                        device_id=self.device_id,
                        message="The device is not responding. Please check the device's power and connections.",
                        error_details=error_msg,
                    )
                )
                await self.websocket.close(code=1011)

                if self.health_manager:
                    await self.health_manager.mark_failure(self.device_id)

                return

            if self.health_manager:
                await self.health_manager.mark_success(self.device_id)

            actual_interval: float = interval or self.monitoring_config.default_single_device_interval

            await self.websocket.send_json(
                MessageBuilder.connection_status(
                    status="connected",
                    device_id=self.device_id,
                    message="The device is connected.",
                    parameters=param_list,
                    interval=actual_interval,
                    support_control=self.monitoring_config.enable_control_commands,
                )
            )

            await self._run_tasks(param_list, actual_interval)

        except WebSocketDisconnect:
            logger.info(f"[{self.device_id}] WebSocket disconnected")
        except Exception as e:
            logger.error(f"[{self.device_id}] Session error: {e}", exc_info=True)
        finally:
            self.manager.disconnect(self.websocket)

    async def _parse_parameters(self, parameters: str | None) -> list[str] | None:
        """
        Parse parameters, send error if failed.

        Returns:
            List of parameters or None if error
        """
        try:
            param_list = parse_parameter_list(parameters, self.device_id, self.config_repo)
            return param_list

        except ParameterParseError as e:
            if "not found" in str(e):
                await self.websocket.send_json(MessageBuilder.device_not_found(self.device_id))
            else:
                await self.websocket.send_json(MessageBuilder.no_parameters_available(self.device_id))
            await self.websocket.close()
            return None

    async def _test_connection(self, param_list: list[str]) -> bool:
        """
        Test device connection, send error if failed.

        Returns:
            True if connection successful, False otherwise
        """
        tester = DeviceConnectionTester(self.service)
        if not await tester.test_and_notify(self.websocket, self.device_id, param_list):
            await self.websocket.close(code=1000, reason="Device offline")
            return False
        return True

    async def _run_tasks(self, param_list: list[str], interval: float) -> None:
        """
        Run monitoring and control tasks concurrently.

        Args:
            param_list: List of parameters to monitor
            interval: Update interval
        """
        # Create task handlers
        monitoring_handler = MonitoringTaskHandler(self.service, self.monitoring_config, self.manager)

        control_handler = ControlCommandHandler(self.service)

        # Create tasks
        monitoring_task = asyncio.create_task(
            monitoring_handler.start_monitoring(self.websocket, self.device_id, param_list, interval)
        )

        control_task = asyncio.create_task(control_handler.handle_commands(self.websocket, self.device_id))

        # Wait for first task to complete
        _, pending = await asyncio.wait([monitoring_task, control_task], return_when=asyncio.FIRST_COMPLETED)

        # Cancel remaining tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


class WebSocketSessionFactory:
    """
    Factory for creating WebSocket device sessions.

    Simplifies session creation with dependency injection.
    """

    def __init__(
        self,
        service: ParameterServiceProtocol,
        config_repo: ConfigRepositoryProtocol,
        manager: ConnectionManagerProtocol,
        monitoring_config: MonitoringConfig | None = None,
    ):
        """Initialize session factory with shared dependencies."""
        self.service = service
        self.config_repo = config_repo
        self.manager = manager
        self.monitoring_config = monitoring_config or MonitoringConfig()

    def create_session(self, websocket: WebSocket, device_id: str) -> WebSocketDeviceSession:
        """
        Create a new WebSocket device session.

        Args:
            websocket: WebSocket connection
            device_id: Device identifier

        Returns:
            WebSocketDeviceSession instance
        """
        return WebSocketDeviceSession(
            websocket=websocket,
            device_id=device_id,
            service=self.service,
            config_repo=self.config_repo,
            manager=self.manager,
            monitoring_config=self.monitoring_config,
        )

    async def run_session(
        self,
        websocket: WebSocket,
        device_id: str,
        parameters: str | None = None,
        interval: float | None = None,
    ) -> None:
        """
        Create and run a session in one call.

        Convenience method for common use case.

        Args:
            websocket: WebSocket connection
            device_id: Device identifier
            parameters: Comma-separated parameter names (optional)
            interval: Update interval (optional)
        """
        session = self.create_session(websocket, device_id)
        await session.run(parameters, interval)
