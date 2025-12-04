"""
Tests for WebSocket device session management.

Tests WebSocketDeviceSession and WebSocketSessionFactory.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from api.websocket.monitoring_config import MonitoringConfig
from api.websocket.session import WebSocketDeviceSession, WebSocketSessionFactory


class MockParameterService:
    """Mock parameter service for testing."""

    def __init__(self):
        self.read_calls = []
        self.write_calls = []

    async def read_multiple_parameters(self, device_id: str, parameters: list[str]):
        """Mock read implementation."""
        self.read_calls.append((device_id, parameters))
        # Return mock ParameterValue objects
        from api.model.responses import ParameterValue

        return [
            ParameterValue(
                type="analog_input",
                name=param,
                value=100.0,
                unit="Hz",
                is_valid=True,
                error_message=None,
            )
            for param in parameters
        ]

    async def write_parameter(self, device_id: str, parameter: str, value: float | int, force: bool = False):
        """Mock write implementation."""
        self.write_calls.append((device_id, parameter, value, force))
        return {
            "success": True,
            "previous_value": 50.0,
            "new_value": value,
            "was_forced": force,
        }


class MockConfigRepository:
    """Mock configuration repository for testing."""

    def __init__(self, devices: dict[str, dict] | None = None):
        self.devices = devices or {"TEST_DEVICE": {"available_parameters": ["frequency", "current"]}}

    def get_device_config(self, device_id: str) -> dict | None:
        """Get device configuration."""
        return self.devices.get(device_id)


class MockConnectionManager:
    """Mock connection manager for testing."""

    def __init__(self):
        self.connections = []
        self.disconnections = []
        self.messages = []

    async def connect(self, websocket):
        """Mock connect."""
        self.connections.append(websocket)

    def disconnect(self, websocket):
        """Mock disconnect."""
        self.disconnections.append(websocket)

    async def send_personal_message(self, message: dict, websocket):
        """Mock send message."""
        self.messages.append((message, websocket))


class TestWebSocketDeviceSession:
    """Test WebSocketDeviceSession class."""

    @pytest.mark.asyncio
    async def test_when_created_then_stores_dependencies(self):
        """Test session stores all dependencies."""
        websocket = AsyncMock()
        service = MockParameterService()
        config_repo = MockConfigRepository()
        manager = MockConnectionManager()
        monitoring_config = MonitoringConfig()

        session = WebSocketDeviceSession(
            websocket=websocket,
            device_id="TEST_DEVICE",
            service=service,
            config_repo=config_repo,
            manager=manager,
            monitoring_config=monitoring_config,
        )

        assert session.websocket is websocket
        assert session.device_id == "TEST_DEVICE"
        assert session.service is service
        assert session.config_repo is config_repo
        assert session.manager is manager
        assert session.monitoring_config is monitoring_config

    @pytest.mark.asyncio
    async def test_when_run_with_valid_params_then_starts_session(self):
        """Test successful session start."""
        websocket = AsyncMock()
        service = MockParameterService()
        config_repo = MockConfigRepository()
        manager = MockConnectionManager()

        session = WebSocketDeviceSession(
            websocket=websocket,
            device_id="TEST_DEVICE",
            service=service,
            config_repo=config_repo,
            manager=manager,
        )

        # Mock _run_tasks to avoid infinite loop
        async def mock_run_tasks(param_list, interval):
            # Simulate quick completion
            pass

        with patch.object(session, "_run_tasks", side_effect=mock_run_tasks):
            await session.run(parameters="frequency", interval=1.0)

        # Verify connection was made
        assert len(manager.connections) == 1

        # Verify connection established message was sent
        assert websocket.send_json.called

    @pytest.mark.asyncio
    async def test_when_device_not_found_then_sends_error(self):
        """Test error when device not found."""
        websocket = AsyncMock()
        service = MockParameterService()
        config_repo = MockConfigRepository(devices={})  # Empty
        manager = MockConnectionManager()

        session = WebSocketDeviceSession(
            websocket=websocket,
            device_id="UNKNOWN_DEVICE",
            service=service,
            config_repo=config_repo,
            manager=manager,
        )

        await session.run(parameters=None, interval=1.0)

        # Verify error message was sent
        websocket.send_json.assert_called()
        call_args = websocket.send_json.call_args[0][0]
        assert call_args["type"] == "error"
        assert call_args["code"] == "DEVICE_NOT_FOUND"

        # Verify websocket was closed
        websocket.close.assert_called()

    @pytest.mark.asyncio
    async def test_when_no_parameters_then_uses_device_config(self):
        """Test using device config when no parameters specified."""
        websocket = AsyncMock()
        service = MockParameterService()
        config_repo = MockConfigRepository()
        manager = MockConnectionManager()

        session = WebSocketDeviceSession(
            websocket=websocket,
            device_id="TEST_DEVICE",
            service=service,
            config_repo=config_repo,
            manager=manager,
        )

        # Mock _run_tasks
        async def mock_run_tasks(param_list, interval):
            assert param_list == ["frequency", "current"]  # From config

        with patch.object(session, "_run_tasks", side_effect=mock_run_tasks):
            await session.run(parameters=None, interval=1.0)

    @pytest.mark.asyncio
    async def test_when_exception_then_cleanup_still_happens(self):
        """Test cleanup happens even when exception occurs."""
        websocket = AsyncMock()
        service = MockParameterService()
        config_repo = MockConfigRepository()
        manager = MockConnectionManager()

        session = WebSocketDeviceSession(
            websocket=websocket,
            device_id="TEST_DEVICE",
            service=service,
            config_repo=config_repo,
            manager=manager,
        )

        # Mock _run_tasks to raise exception
        async def mock_run_tasks_error(param_list, interval):
            raise RuntimeError("Test error")

        with patch.object(session, "_run_tasks", side_effect=mock_run_tasks_error):
            # Should not raise, error is caught
            await session.run(parameters="frequency", interval=1.0)

        # Verify cleanup happened (disconnect was called)
        assert len(manager.disconnections) == 1

    @pytest.mark.asyncio
    async def test_when_interval_not_specified_then_uses_default(self):
        """Test using default interval when not specified."""
        websocket = AsyncMock()
        service = MockParameterService()
        config_repo = MockConfigRepository()
        manager = MockConnectionManager()
        monitoring_config = MonitoringConfig(default_single_device_interval=5.0)

        session = WebSocketDeviceSession(
            websocket=websocket,
            device_id="TEST_DEVICE",
            service=service,
            config_repo=config_repo,
            manager=manager,
            monitoring_config=monitoring_config,
        )

        # Mock _run_tasks to check interval
        async def mock_run_tasks(param_list, interval):
            assert interval == 5.0  # Should use default

        with patch.object(session, "_run_tasks", side_effect=mock_run_tasks):
            await session.run(parameters="frequency", interval=None)


class TestWebSocketSessionFactory:
    """Test WebSocketSessionFactory class."""

    def test_when_created_then_stores_dependencies(self):
        """Test factory stores shared dependencies."""
        service = MockParameterService()
        config_repo = MockConfigRepository()
        manager = MockConnectionManager()
        monitoring_config = MonitoringConfig()

        factory = WebSocketSessionFactory(
            service=service,
            config_repo=config_repo,
            manager=manager,
            monitoring_config=monitoring_config,
        )

        assert factory.service is service
        assert factory.config_repo is config_repo
        assert factory.manager is manager
        assert factory.monitoring_config is monitoring_config

    def test_when_create_session_then_returns_session(self):
        """Test creating a session from factory."""
        service = MockParameterService()
        config_repo = MockConfigRepository()
        manager = MockConnectionManager()

        factory = WebSocketSessionFactory(
            service=service,
            config_repo=config_repo,
            manager=manager,
        )

        websocket = AsyncMock()
        session = factory.create_session(websocket, "TEST_DEVICE")

        assert isinstance(session, WebSocketDeviceSession)
        assert session.device_id == "TEST_DEVICE"
        assert session.websocket is websocket
        assert session.service is service
        assert session.config_repo is config_repo
        assert session.manager is manager

    @pytest.mark.asyncio
    async def test_when_run_session_then_creates_and_runs(self):
        """Test run_session convenience method."""
        service = MockParameterService()
        config_repo = MockConfigRepository()
        manager = MockConnectionManager()

        factory = WebSocketSessionFactory(
            service=service,
            config_repo=config_repo,
            manager=manager,
        )

        websocket = AsyncMock()

        # Mock the session.run method
        with patch.object(WebSocketDeviceSession, "run", new_callable=AsyncMock) as mock_run:
            await factory.run_session(websocket, "TEST_DEVICE", parameters="frequency", interval=1.0)

            # Assert
            mock_run.assert_called_once_with("frequency", 1.0)

    def test_when_no_monitoring_config_then_uses_default(self):
        """Test factory uses default config when not provided."""
        service = MockParameterService()
        config_repo = MockConfigRepository()
        manager = MockConnectionManager()

        factory = WebSocketSessionFactory(
            service=service,
            config_repo=config_repo,
            manager=manager,
            monitoring_config=None,  # Not provided
        )

        # Should create default config
        assert factory.monitoring_config is not None
        assert isinstance(factory.monitoring_config, MonitoringConfig)


class TestSessionIntegration:
    """Integration tests for session components."""

    @pytest.mark.asyncio
    async def test_when_complete_flow_then_all_steps_executed(self):
        """Test complete session flow."""
        websocket = AsyncMock()
        service = MockParameterService()
        config_repo = MockConfigRepository()
        manager = MockConnectionManager()

        session = WebSocketDeviceSession(
            websocket=websocket,
            device_id="TEST_DEVICE",
            service=service,
            config_repo=config_repo,
            manager=manager,
        )

        # Mock _run_tasks to complete quickly
        async def mock_run_tasks(param_list, interval):
            pass

        with patch.object(session, "_run_tasks", side_effect=mock_run_tasks):
            await session.run(parameters="frequency", interval=1.0)

        # Verify the flow
        assert len(manager.connections) == 1  # Connected
        assert websocket.send_json.called  # Sent connection message
        assert len(service.read_calls) > 0  # Connection test read
        assert len(manager.disconnections) == 1  # Disconnected in cleanup

    @pytest.mark.asyncio
    async def test_when_exception_during_run_then_cleanup_still_executed(self):
        """Test cleanup happens even if exception occurs."""
        websocket = AsyncMock()
        service = MockParameterService()
        config_repo = MockConfigRepository()
        manager = MockConnectionManager()

        session = WebSocketDeviceSession(
            websocket=websocket,
            device_id="TEST_DEVICE",
            service=service,
            config_repo=config_repo,
            manager=manager,
        )

        # Mock _run_tasks to raise exception
        async def mock_run_tasks_error(param_list, interval):
            raise RuntimeError("Test error")

        with patch.object(session, "_run_tasks", side_effect=mock_run_tasks_error):
            # Should not raise, error is caught and logged
            await session.run(parameters="frequency", interval=1.0)

        # Verify cleanup still happened
        assert len(manager.disconnections) == 1
