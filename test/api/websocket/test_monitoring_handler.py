"""
Tests for MonitoringTaskHandler.

Tests monitoring loop logic following Talos patterns.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from api.model.responses import ParameterValue
from api.websocket.config import MonitoringConfig
from api.websocket.monitoring_handler import MonitoringTaskHandler, MultiDeviceMonitoringHandler


class MockParameterService:
    """Mock parameter service for testing."""

    def __init__(self, should_succeed: bool = True, values: list[dict] | None = None):
        self.should_succeed = should_succeed
        self.values = values or []
        self.read_calls = []

    async def read_multiple_parameters(self, device_id: str, parameters: list[str]) -> list[ParameterValue]:
        """Mock read implementation."""
        self.read_calls.append((device_id, parameters))

        if not self.values:
            # Default behavior
            if self.should_succeed:
                return [
                    ParameterValue(
                        type="analog_input",
                        name=p,
                        value=100.0,
                        unit="Hz",
                        is_valid=True,
                        error_message=None,
                    )
                    for p in parameters
                ]
            else:
                return [
                    ParameterValue(
                        type="analog_input",
                        name=p,
                        value=-1,
                        unit="",
                        is_valid=False,
                        error_message="Read failed",
                    )
                    for p in parameters
                ]
        else:
            # Use provided values
            return [
                ParameterValue(
                    type="analog_input",
                    name=v["name"],
                    value=v["value"],
                    unit=v.get("unit", ""),
                    is_valid=v.get("is_valid", True),
                    error_message=v.get("error_message"),
                )
                for v in self.values
            ]


class TestMonitoringTaskHandler:
    """Test MonitoringTaskHandler class."""

    def test_when_created_then_stores_dependencies(self):
        """Test handler stores dependencies."""
        service = MockParameterService()
        config = MonitoringConfig()

        handler = MonitoringTaskHandler(service, config)

        assert handler.service is service
        assert handler.config is config

    def test_when_created_then_initial_state_correct(self):
        """Test initial state."""
        service = MockParameterService()
        config = MonitoringConfig()

        handler = MonitoringTaskHandler(service, config)

        assert handler.is_running is False
        assert handler.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_when_process_parameter_values_then_returns_correct_dict(self):
        """Test parameter value processing."""
        service = MockParameterService()
        config = MonitoringConfig()
        handler = MonitoringTaskHandler(service, config)

        param_values = [
            ParameterValue(
                type="analog_input",
                name="frequency",
                value=50.0,
                unit="Hz",
                is_valid=True,
                error_message=None,
            ),
            ParameterValue(
                type="analog_input",
                name="current",
                value=-1,
                unit="A",
                is_valid=False,
                error_message="Sensor error",
            ),
        ]

        data, errors = handler._process_parameter_values(param_values)

        # Assert
        assert "frequency" in data
        assert data["frequency"]["value"] == 50.0
        assert data["frequency"]["unit"] == "Hz"
        assert "current" not in data
        assert errors is not None
        assert len(errors) == 1
        assert "current: Sensor error" in errors

    @pytest.mark.asyncio
    async def test_when_all_valid_then_no_errors_key(self):
        """Test no errors key when all values valid."""
        service = MockParameterService()
        config = MonitoringConfig()
        handler = MonitoringTaskHandler(service, config)

        param_values = [
            ParameterValue(
                type="analog_input",
                name="frequency",
                value=50.0,
                unit="Hz",
                is_valid=True,
                error_message=None,
            )
        ]

        data, errors = handler._process_parameter_values(param_values)

        assert "frequency" in data
        assert errors is None

    @pytest.mark.asyncio
    async def test_when_start_monitoring_then_reads_parameters(self):
        """Test monitoring reads parameters."""
        service = MockParameterService(should_succeed=True)
        config = MonitoringConfig()
        handler = MonitoringTaskHandler(service, config)

        websocket = AsyncMock()

        async def run_and_cancel():
            task = asyncio.create_task(handler.start_monitoring(websocket, "TEST_DEVICE", ["param1"], interval=0.1))
            await asyncio.sleep(0.25)  # Let it run for a bit
            handler.stop()
            await task

        await run_and_cancel()

        # Should have made at least one read
        assert len(service.read_calls) >= 1
        assert service.read_calls[0] == ("TEST_DEVICE", ["param1"])

    @pytest.mark.asyncio
    async def test_when_stop_called_then_monitoring_stops(self):
        """Test stop() stops monitoring."""
        service = MockParameterService()
        config = MonitoringConfig()
        handler = MonitoringTaskHandler(service, config)

        websocket = AsyncMock()

        task = asyncio.create_task(handler.start_monitoring(websocket, "TEST_DEVICE", ["param1"], interval=0.1))

        await asyncio.sleep(0.05)
        assert handler.is_running is True

        handler.stop()
        await asyncio.sleep(0.15)

        assert handler.is_running is False


class TestMultiDeviceMonitoringHandler:
    """Test MultiDeviceMonitoringHandler class."""

    @pytest.mark.asyncio
    async def test_when_start_monitoring_multiple_devices_then_sends_updates(self):
        """Test multi-device monitoring sends updates."""
        service = MockParameterService(should_succeed=True)
        handler = MultiDeviceMonitoringHandler(service, connection_manager=None)  # 明確不用 manager

        websocket = AsyncMock()
        device_params = {
            "DEVICE_01": ["param1"],
            "DEVICE_02": ["param2"],
        }

        async def run_briefly():
            task = asyncio.create_task(handler.start_monitoring(websocket, device_params, interval=0.1))
            await asyncio.sleep(0.2)
            handler.stop()
            await task

        await run_briefly()

        # Should have sent at least one update
        websocket.send_json.assert_called()
        call_args = websocket.send_json.call_args[0][0]

        assert call_args["type"] == "data"
        assert "devices" in call_args

    @pytest.mark.asyncio
    async def test_when_start_monitoring_then_sends_updates(self):
        """Test multi-device monitoring sends updates."""
        service = MockParameterService(should_succeed=True)
        handler = MultiDeviceMonitoringHandler(service, connection_manager=None)

        websocket = AsyncMock()
        device_params = {"DEVICE_01": ["param1"]}

        async def run_briefly():
            task = asyncio.create_task(handler.start_monitoring(websocket, device_params, interval=0.1))
            await asyncio.sleep(0.2)
            handler.stop()
            await task

        await run_briefly()

        # Should have sent at least one update
        assert websocket.send_json.call_count >= 1

        # Verify message structure
        call_args = websocket.send_json.call_args[0][0]
        assert call_args["type"] == "data"
        assert "devices" in call_args
