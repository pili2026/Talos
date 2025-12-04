"""
Device connection testing for WebSocket monitoring.

Handles connection validation and error notification,
following Talos patterns for industrial IoT reliability.
"""

import asyncio
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
        Test device connection using fast batch testing.

        Uses Core's optimized fast_test_device_connection which:
        - Tests multiple parameters (up to 5)
        - Uses short timeout (0.8s per parameter)
        - Requires 30% success rate

        Args:
            device_id: Device identifier
            test_parameters: List of parameters (used to determine count)

        Returns:
            Tuple of (success, error_message)
        """
        if not test_parameters:
            return False, "No parameters available for testing"

        try:
            # Determine how many parameters to test
            test_count = min(5, len(test_parameters))

            logger.info(f"[{device_id}] Testing connection with up to {test_count} parameters")

            if hasattr(self.service, "fast_test_device_connection"):
                success, error, details = await self.service.fast_test_device_connection(
                    device_id, test_param_count=test_count, min_success_rate=0.3
                )

                if success:
                    logger.info(
                        f"[{device_id}] ✓ Connection test passed: "
                        f"{details['passed']}/{details['tested']} parameters "
                        f"({details['rate']:.0%}) in {details['elapsed_seconds']}s"
                    )
                else:
                    logger.error(f"[{device_id}] Connection test failed: {error}")

                return success, error

            else:
                # Fallback to old method if fast test not available
                logger.warning(f"[{device_id}] fast_test_device_connection not available, " f"using legacy test method")
                return await self._legacy_test_connection(device_id, test_parameters)

        except Exception as e:
            logger.error(f"[{device_id}] Connection test error: {e}", exc_info=True)
            return False, f"Connection test error: {str(e)}"

    async def test_and_notify(self, websocket: WebSocket, device_id: str, test_parameters: list[str]) -> bool:
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
            await websocket.send_json(
                MessageBuilder.connection_status(
                    status="device_offline",
                    device_id=device_id,
                    message="The device is not responding. Please check the device's power and connections",
                    error_details=error,
                    suggestion="Please ensure the device is powered on and properly connected to the Modbus bus.",
                )
            )
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

        async def test_one(device_id: str, params: list[str]):
            result = await self.test_connection(device_id, params)
            return device_id, result

        tasks = [test_one(dev_id, params) for dev_id, params in device_configs.items()]
        results = await asyncio.gather(*tasks)

        return dict(results)

    async def _legacy_test_connection(self, device_id: str, test_parameters: list[str]) -> tuple[bool, str | None]:
        """Legacy test method (fallback)."""
        test_param = test_parameters[0]
        try:
            result = await asyncio.wait_for(self.service.read_multiple_parameters(device_id, [test_param]), timeout=2.0)

            if not result or not any(pv.is_valid for pv in result):
                return False, "Device not responding"

            return True, None

        except asyncio.TimeoutError:
            return False, "Device timeout"
        except Exception as e:
            return False, str(e)


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
