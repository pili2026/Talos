"""
Tests for ControlCommandHandler.

Tests control command handling logic following Talos patterns.
"""

from unittest.mock import AsyncMock

import pytest

from api.websocket.control_handler import ControlCommandHandler, WriteCommand


class MockParameterService:
    """Mock parameter service for testing."""

    def __init__(self, write_result: dict | None = None):
        self.write_result = write_result or {"success": True}
        self.write_calls = []

    async def write_parameter(self, device_id: str, parameter: str, value: float | int, force: bool = False) -> dict:
        """Mock write implementation."""
        self.write_calls.append((device_id, parameter, value, force))
        return self.write_result


class TestControlCommandHandler:
    """Test ControlCommandHandler class."""

    def test_when_created_then_stores_service(self):
        """Test handler stores parameter service."""
        service = MockParameterService()

        handler = ControlCommandHandler(service)

        assert handler.service is service

    def test_when_created_then_initial_state_correct(self):
        """Test initial state."""
        service = MockParameterService()

        handler = ControlCommandHandler(service)

        assert handler.is_running is False

    @pytest.mark.asyncio
    async def test_when_write_command_valid_then_executes(self):
        """Test valid write command execution."""
        service = MockParameterService(
            write_result={
                "success": True,
                "new_value": 50,
                "previous_value": 30,
                "was_forced": False,
            }
        )
        handler = ControlCommandHandler(service)

        websocket = AsyncMock()
        message = {
            "action": "write",
            "parameter": "frequency",
            "value": 50,
            "force": False,
        }

        await handler._handle_write_command(websocket, "TEST_DEVICE", message)

        # Should have called write
        assert len(service.write_calls) == 1
        assert service.write_calls[0] == ("TEST_DEVICE", "frequency", 50, False)

        # Should have sent response
        websocket.send_json.assert_called_once()
        response = websocket.send_json.call_args[0][0]
        assert response["type"] == "write_result"
        assert response["success"] is True

    @pytest.mark.asyncio
    async def test_when_write_command_with_force_then_passes_force_flag(self):
        """Test write command with force flag."""
        service = MockParameterService(
            write_result={
                "success": True,
                "new_value": 50,
                "was_forced": True,
            }
        )
        handler = ControlCommandHandler(service)

        websocket = AsyncMock()
        message = {
            "action": "write",
            "parameter": "frequency",
            "value": 50,
            "force": True,
        }

        await handler._handle_write_command(websocket, "TEST_DEVICE", message)

        # Should have called write with force=True
        assert service.write_calls[0] == ("TEST_DEVICE", "frequency", 50, True)

        # Response should indicate forced
        response = websocket.send_json.call_args[0][0]
        assert response["was_forced"] is True

    @pytest.mark.asyncio
    async def test_when_write_command_missing_parameter_then_sends_error(self):
        """Test write command with missing parameter."""
        service = MockParameterService()
        handler = ControlCommandHandler(service)

        websocket = AsyncMock()
        message = {"action": "write", "value": 50}  # Missing parameter

        await handler._handle_write_command(websocket, "TEST_DEVICE", message)

        # Should NOT have called write
        assert len(service.write_calls) == 0

        # Should have sent error
        websocket.send_json.assert_called_once()
        response = websocket.send_json.call_args[0][0]
        assert response["type"] == "error"
        assert response["code"] == "INVALID_WRITE_REQUEST"

    @pytest.mark.asyncio
    async def test_when_write_command_missing_value_then_sends_error(self):
        """Test write command with missing value."""
        service = MockParameterService()
        handler = ControlCommandHandler(service)

        websocket = AsyncMock()
        message = {"action": "write", "parameter": "frequency"}  # Missing value

        await handler._handle_write_command(websocket, "TEST_DEVICE", message)

        # Should NOT have called write
        assert len(service.write_calls) == 0

        # Should have sent error
        websocket.send_json.assert_called_once()
        response = websocket.send_json.call_args[0][0]
        assert response["type"] == "error"

    @pytest.mark.asyncio
    async def test_when_write_fails_then_sends_failure_message(self):
        """Test write command failure."""
        service = MockParameterService(write_result={"success": False, "error": "Device not responding"})
        handler = ControlCommandHandler(service)

        websocket = AsyncMock()
        message = {"action": "write", "parameter": "frequency", "value": 50}

        await handler._handle_write_command(websocket, "TEST_DEVICE", message)

        # Should have sent failure response
        response = websocket.send_json.call_args[0][0]
        assert response["type"] == "write_result"
        assert response["success"] is False
        assert "Device not responding" in response["error"]

    @pytest.mark.asyncio
    async def test_when_write_raises_exception_then_sends_error(self):
        """Test write command exception handling."""

        class FailingService:
            async def write_parameter(self, device_id, parameter, value, force=False):
                raise RuntimeError("Connection lost")

        handler = ControlCommandHandler(FailingService())

        websocket = AsyncMock()
        message = {"action": "write", "parameter": "frequency", "value": 50}

        await handler._handle_write_command(websocket, "TEST_DEVICE", message)

        # Should have sent failure response with exception message
        response = websocket.send_json.call_args[0][0]
        assert response["type"] == "write_result"
        assert response["success"] is False
        assert "Connection lost" in response["error"]

    @pytest.mark.asyncio
    async def test_when_ping_command_then_sends_pong(self):
        """Test ping command."""
        service = MockParameterService()
        handler = ControlCommandHandler(service)

        websocket = AsyncMock()

        await handler._handle_ping_command(websocket)

        websocket.send_json.assert_called_once()
        response = websocket.send_json.call_args[0][0]
        assert response["type"] == "pong"

    @pytest.mark.asyncio
    async def test_when_unknown_action_then_sends_unknown_action(self):
        """Test unknown command."""
        service = MockParameterService()
        handler = ControlCommandHandler(service)

        websocket = AsyncMock()

        await handler._handle_unknown_action(websocket, "invalid_action")

        websocket.send_json.assert_called_once()
        response = websocket.send_json.call_args[0][0]
        assert response["type"] == "error"
        assert response["code"] == "UNKNOWN_ACTION"

    def test_when_stop_called_then_sets_flag(self):
        """Test stop() sets running flag."""
        service = MockParameterService()
        handler = ControlCommandHandler(service)

        handler._is_running = True
        handler.stop()

        assert handler.is_running is False


class TestWriteCommand:
    """Test WriteCommand helper class."""

    def test_when_created_then_stores_values(self):
        """Test WriteCommand stores all values."""
        cmd = WriteCommand(device_id="VFD_01", parameter="frequency", value=50.0, force=True)

        assert cmd.device_id == "VFD_01"
        assert cmd.parameter == "frequency"
        assert cmd.value == 50.0
        assert cmd.force is True

    def test_when_created_without_force_then_defaults_false(self):
        """Test force defaults to False."""
        cmd = WriteCommand(device_id="VFD_01", parameter="frequency", value=50.0)

        assert cmd.force is False

    def test_when_from_message_valid_then_creates_command(self):
        """Test creating from valid message."""
        message = {"parameter": "frequency", "value": 50, "force": True}

        cmd = WriteCommand.from_message("VFD_01", message)

        assert cmd.device_id == "VFD_01"
        assert cmd.parameter == "frequency"
        assert cmd.value == 50
        assert cmd.force is True

    def test_when_from_message_without_force_then_defaults_false(self):
        """Test from_message with force not specified."""
        message = {"parameter": "frequency", "value": 50}

        cmd = WriteCommand.from_message("VFD_01", message)

        assert cmd.force is False

    def test_when_from_message_missing_parameter_then_raises_error(self):
        """Test from_message with missing parameter."""
        message = {"value": 50}

        with pytest.raises(ValueError, match="Missing required fields"):
            WriteCommand.from_message("VFD_01", message)

    def test_when_from_message_missing_value_then_raises_error(self):
        """Test from_message with missing value."""
        message = {"parameter": "frequency"}

        with pytest.raises(ValueError, match="Missing required fields"):
            WriteCommand.from_message("VFD_01", message)

    def test_when_repr_then_shows_details(self):
        """Test string representation."""
        cmd = WriteCommand(device_id="VFD_01", parameter="frequency", value=50.0, force=True)

        repr_str = repr(cmd)

        assert "VFD_01" in repr_str
        assert "frequency" in repr_str
        assert "50" in repr_str
        assert "force=True" in repr_str
