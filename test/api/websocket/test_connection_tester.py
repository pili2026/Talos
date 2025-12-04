"""
Tests for DeviceConnectionTester.

Tests device connection testing logic following Talos patterns.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from api.model.responses import ParameterValue
from api.websocket.connection_tester import ConnectionTestResult, DeviceConnectionTester


class MockParameterService:
    """Mock parameter service for testing."""

    def __init__(self, should_succeed: bool = True, should_raise: bool = False):
        self.should_succeed = should_succeed
        self.should_raise = should_raise
        self.read_calls = []

    async def read_multiple_parameters(self, device_id: str, parameters: list[str]) -> list[ParameterValue]:
        """Mock read implementation."""
        self.read_calls.append((device_id, parameters))

        if self.should_raise:
            raise RuntimeError("Device communication error")

        if self.should_succeed:
            return [
                ParameterValue(
                    type="analog_input",
                    name=parameters[0],
                    value=100.0,
                    unit="Hz",
                    is_valid=True,
                    error_message=None,
                )
            ]
        else:
            return [
                ParameterValue(
                    type="analog_input",
                    name=parameters[0],
                    value=-1,
                    unit="",
                    is_valid=False,
                    error_message="Read failed",
                )
            ]


class TestDeviceConnectionTester:
    """Test DeviceConnectionTester class."""

    def test_when_created_then_stores_service(self):
        """Test tester stores parameter service."""
        service = MockParameterService()
        tester = DeviceConnectionTester(service)

        assert tester.service is service

    @pytest.mark.asyncio
    async def test_when_valid_connection_then_returns_success(self):
        """Test successful connection returns True."""
        service = MockParameterService(should_succeed=True)
        tester = DeviceConnectionTester(service)

        success, error = await tester.test_connection("TEST_DEVICE", ["param1"])

        assert success is True
        assert error is None
        assert service.read_calls == [("TEST_DEVICE", ["param1"])]

    @pytest.mark.asyncio
    async def test_when_device_not_responding_then_returns_failure(self):
        """Test non-responding device returns False."""
        service = MockParameterService(should_succeed=False)
        tester = DeviceConnectionTester(service)

        success, error = await tester.test_connection("TEST_DEVICE", ["param1"])

        assert success is False
        assert error == "Device not responding"

    @pytest.mark.asyncio
    async def test_when_no_parameters_then_returns_failure(self):
        """Test no parameters returns appropriate error."""
        service = MockParameterService()
        tester = DeviceConnectionTester(service)

        success, error = await tester.test_connection("TEST_DEVICE", [])

        assert success is False
        assert error == "No parameters available for testing"
        assert len(service.read_calls) == 0  # Should not attempt read

    @pytest.mark.asyncio
    async def test_when_exception_raised_then_returns_failure(self):
        """Test exception during read returns failure."""
        service = MockParameterService(should_raise=True)
        tester = DeviceConnectionTester(service)

        success, error = await tester.test_connection("TEST_DEVICE", ["param1"])

        assert success is False
        assert "Connection error:" in error
        assert "Device communication error" in error

    @pytest.mark.asyncio
    async def test_when_test_and_notify_success_then_returns_true(self):
        """Test test_and_notify returns True on success."""
        service = MockParameterService(should_succeed=True)
        tester = DeviceConnectionTester(service)
        websocket = AsyncMock()

        result = await tester.test_and_notify(websocket, "TEST_DEVICE", ["param1"])

        assert result is True
        # No error message should be sent
        websocket.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_test_and_notify_fails_then_sends_error(self):
        """Test test_and_notify sends error on failure."""
        service = MockParameterService(should_succeed=False)
        tester = DeviceConnectionTester(service)
        websocket = AsyncMock()

        result = await tester.test_and_notify(websocket, "TEST_DEVICE", ["param1"])

        assert result is False
        # Error message should be sent
        websocket.send_json.assert_called_once()
        error_msg = websocket.send_json.call_args[0][0]
        assert error_msg["type"] == "error"

    @pytest.mark.asyncio
    async def test_when_test_and_notify_no_params_then_sends_specific_error(self):
        """Test test_and_notify sends specific error for no parameters."""
        service = MockParameterService()
        tester = DeviceConnectionTester(service)
        websocket = AsyncMock()

        result = await tester.test_and_notify(websocket, "TEST_DEVICE", [])

        assert result is False
        websocket.send_json.assert_called_once()
        error_msg = websocket.send_json.call_args[0][0]
        assert error_msg["type"] == "error"
        assert error_msg["code"] == "NO_PARAMETERS"

    @pytest.mark.asyncio
    async def test_when_multiple_devices_then_tests_all(self):
        """Test test_multiple_devices tests all devices."""
        service = MockParameterService(should_succeed=True)
        tester = DeviceConnectionTester(service)

        configs = {
            "DEVICE_01": ["param1"],
            "DEVICE_02": ["param2"],
            "DEVICE_03": ["param3"],
        }

        results = await tester.test_multiple_devices(configs)

        assert len(results) == 3
        assert all(success for success, _ in results.values())
        assert len(service.read_calls) == 3

    @pytest.mark.asyncio
    async def test_when_multiple_devices_with_failures_then_reports_each(self):
        """Test test_multiple_devices reports individual failures."""
        # Create service that fails on second device
        call_count = 0

        async def mock_read(device_id, params):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return [
                    ParameterValue(
                        type="analog_input",
                        name="p",
                        value=-1,
                        unit="",
                        is_valid=False,
                        error_message="Failed",
                    )
                ]
            return [
                ParameterValue(type="analog_input", name="p", value=100, unit="Hz", is_valid=True, error_message=None)
            ]

        service = Mock()
        service.read_multiple_parameters = mock_read

        tester = DeviceConnectionTester(service)

        configs = {
            "DEVICE_01": ["param1"],
            "DEVICE_02": ["param2"],  # This will fail
            "DEVICE_03": ["param3"],
        }

        results = await tester.test_multiple_devices(configs)

        assert results["DEVICE_01"][0] is True
        assert results["DEVICE_02"][0] is False
        assert results["DEVICE_03"][0] is True


class TestConnectionTestResult:
    """Test ConnectionTestResult helper class."""

    def test_when_successful_then_properties_correct(self):
        """Test successful result properties."""
        result = ConnectionTestResult(True)

        assert result.is_successful is True
        assert result.has_error is False
        assert bool(result) is True
        assert result.error_message is None

    def test_when_failed_then_properties_correct(self):
        """Test failed result properties."""
        result = ConnectionTestResult(False, "Connection timeout")

        assert result.is_successful is False
        assert result.has_error is True
        assert bool(result) is False
        assert result.error_message == "Connection timeout"

    def test_when_repr_then_shows_status(self):
        """Test string representation."""
        success_result = ConnectionTestResult(True)
        fail_result = ConnectionTestResult(False, "Error")

        assert "success=True" in repr(success_result)
        assert "success=False" in repr(fail_result)
        assert "Error" in repr(fail_result)
