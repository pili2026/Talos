"""
Device connection testing for WebSocket monitoring.

Handles connection validation and error notification,
following Talos patterns for industrial IoT reliability.
"""

import logging
from typing import Protocol

from fastapi import WebSocket

from api.model.responses import ParameterValue
from api.websocket.message_builder import MessageBuilder

logger = logging.getLogger(__name__)


class ParameterServiceProtocol(Protocol):
    """Protocol for parameter service dependency."""

    async def read_multiple_parameters(self, device_id: str, parameters: list[str]) -> list[ParameterValue]:
        """Read multiple parameters from a device."""
        ...


class DeviceConnectionTester:
    """
    Tests device connectivity before establishing WebSocket monitoring.

    Follows Talos principle: Verify device availability before committing
    to long-running monitoring connections.

    Example:
        >>> tester = DeviceConnectionTester(parameter_service)
        >>> success = await tester.test_connection(device_id, ["param1"])
        >>> if success:
        ...     # Proceed with monitoring
    """

    def __init__(self, parameter_service: ParameterServiceProtocol):
        """
        Initialize connection tester.

        Args:
            parameter_service: Service for reading device parameters
        """
        self.service = parameter_service

    async def test_connection(self, device_id: str, test_parameters: list[str]) -> tuple[bool, str | None]:
        """
        Test device connection by attempting to read a parameter.

        Args:
            device_id: Device identifier
            test_parameters: List of parameters available for testing

        Returns:
            Tuple of (success, error_message)
            - If successful: (True, None)
            - If failed: (False, "error description")

        Example:
            >>> success, error = await tester.test_connection("VFD_01", ["frequency"])
            >>> if not success:
            ...     print(f"Connection failed: {error}")
        """
        if not test_parameters:
            return False, "No parameters available for testing"

        try:
            logger.info(f"Testing connection to device {device_id}...")

            # Use first parameter for connection test
            test_param = test_parameters[0]
            result = await self.service.read_multiple_parameters(device_id, [test_param])

            # Check if any valid data was received
            if not result or not any(pv.is_valid for pv in result):
                logger.error(f"[{device_id}] Connection test failed - no valid data")
                return False, "Device not responding"

            logger.info(f"[{device_id}] ✓ Connection test successful")
            return True, None

        except Exception as e:
            logger.error(f"[{device_id}] Connection test error: {e}", exc_info=True)
            return False, f"Connection error: {str(e)}"

    async def test_and_notify(
        self,
        websocket: WebSocket,
        device_id: str,
        test_parameters: list[str],
    ) -> bool:
        """
        Test connection and automatically send error message to WebSocket if failed.

        This is the recommended method for WebSocket endpoints as it handles
        both testing and error notification in one call.

        Args:
            websocket: WebSocket connection to notify
            device_id: Device identifier
            test_parameters: List of parameters available for testing

        Returns:
            True if connection successful, False if failed

        Side Effects:
            - Sends error message to websocket if connection fails
            - Logs connection test results

        Example:
            >>> tester = DeviceConnectionTester(service)
            >>> if not await tester.test_and_notify(websocket, device_id, params):
            ...     await websocket.close(code=1011)
            ...     return  # Exit early, error already sent
        """
        # Check for no parameters first
        if not test_parameters:
            await websocket.send_json(MessageBuilder.no_parameters_available(device_id))
            return False

        # Test connection
        success, error = await self.test_connection(device_id, test_parameters)

        if not success:
            # Send appropriate error message
            if "not responding" in error.lower():
                await websocket.send_json(MessageBuilder.connection_failed(device_id, error))
            else:
                await websocket.send_json(MessageBuilder.connection_error(device_id, error))
            return False

        return True

    async def test_multiple_devices(self, device_configs: dict[str, list[str]]) -> dict[str, tuple[bool, str | None]]:
        """
        Test connections to multiple devices concurrently.

        Useful for multi-device monitoring endpoints to fail fast if any
        devices are unreachable.

        Args:
            device_configs: Dict mapping device_id to list of test parameters

        Returns:
            Dict mapping device_id to (success, error_message)

        Example:
            >>> configs = {
            ...     "VFD_01": ["frequency"],
            ...     "VFD_02": ["frequency"],
            ... }
            >>> results = await tester.test_multiple_devices(configs)
            >>> failed = [dev for dev, (ok, _) in results.items() if not ok]
        """
        import asyncio

        async def test_one(device_id: str, params: list[str]):
            result = await self.test_connection(device_id, params)
            return device_id, result

        tasks = [test_one(dev_id, params) for dev_id, params in device_configs.items()]
        results = await asyncio.gather(*tasks)

        return dict(results)


class ConnectionTestResult:
    """
    Structured result from connection test.

    Provides a more explicit API than tuple returns.
    """

    def __init__(self, success: bool, error_message: str | None = None):
        self.success = success
        self.error_message = error_message

    @property
    def is_successful(self) -> bool:
        """Check if connection test was successful."""
        return self.success

    @property
    def has_error(self) -> bool:
        """Check if connection test failed."""
        return not self.success

    def __bool__(self) -> bool:
        """Allow boolean evaluation: if result: ..."""
        return self.success

    def __repr__(self) -> str:
        if self.success:
            return "ConnectionTestResult(success=True)"
        return f"ConnectionTestResult(success=False, error={self.error_message!r})"
