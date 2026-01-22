"""
Test ProvisionRouter endpoints

Integration tests for API endpoints.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from api.app import create_application
from api.app_state import TalosAppState
from api.model.provision import ProvisionCurrentConfig, ProvisionRebootResult, ProvisionSetConfigResult
from api.service.provision_service import ProvisionService
from core.schema.system_config_schema import SystemConfig


@pytest.fixture
def mock_provision_service():
    """Create mock ProvisionService"""
    mock = MagicMock(spec=ProvisionService)

    # Mock synchronous method with proper return value
    mock.get_current_config.return_value = ProvisionCurrentConfig(
        hostname="talos000001",
        reverse_port=8621,
        port_source="service",
    )

    # Mock async method - use AsyncMock for proper async support
    mock.set_config = AsyncMock(
        return_value=ProvisionSetConfigResult(
            success=True,
            requires_reboot=False,
            changes=[],
            message="Configuration updated",
        )
    )

    mock.trigger_reboot = AsyncMock(
        return_value=ProvisionRebootResult(
            success=True,
            message="System reboot initiated",
        )
    )

    return mock


@pytest.fixture
def client(mock_provision_service):
    """Create test client with mocked ProvisionService"""
    app = create_application()

    # Initialize app state properly
    app.state.talos = TalosAppState(unified_mode=False)

    # Mock SystemConfig
    system_config = SystemConfig(
        MONITOR_INTERVAL_SECONDS=1.0,
        REMOTE_ACCESS={"REVERSE_SSH": {"PORT": 8621}},
        PATHS={"STATE_DIR": "/tmp"},
        SUBSCRIBERS={},
    )

    app.state.talos.system_config = system_config
    app.state.talos.provision_service = mock_provision_service

    return TestClient(app), mock_provision_service


class TestGetConfig:
    """Test GET /api/provision/config endpoint"""

    def test_when_success_then_returns_current_config(self, client):
        """Test successful config retrieval"""
        test_client, mock_service = client

        response = test_client.get("/api/provision/config")

        assert response.status_code == 200
        data = response.json()
        assert data["hostname"] == "talos000001"
        assert data["reverse_port"] == 8621
        assert data["port_source"] == "service"

        # Verify service was called
        mock_service.get_current_config.assert_called_once()

    def test_when_service_error_then_returns_500(self, client):
        """Test error handling"""
        test_client, mock_service = client

        # Override mock to raise exception
        mock_service.get_current_config.side_effect = RuntimeError("Service error")

        response = test_client.get("/api/provision/config")

        assert response.status_code == 500
        # Accept both error formats
        error_data = response.json()
        error_msg = error_data.get("detail") or error_data.get("message") or str(error_data)
        assert "Service error" in error_msg


class TestSetConfig:
    """Test POST /api/provision/config endpoint"""

    def test_when_valid_input_then_updates_config(self, client):
        """Test successful config update"""
        test_client, mock_service = client

        # Configure mock to return specific result
        mock_service.set_config.return_value = ProvisionSetConfigResult(
            success=True,
            requires_reboot=True,
            changes=["hostname"],
            message="Configuration updated successfully",
        )

        response = test_client.post(
            "/api/provision/config",
            json={"hostname": "talos000002", "reverse_port": 8621},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["requires_reboot"] is True
        assert "hostname" in data["changes"]

        # Verify service was called with correct arguments
        mock_service.set_config.assert_called_once_with("talos000002", 8621)

    def test_when_both_changed_then_returns_both_changes(self, client):
        """Test updating both hostname and port"""
        test_client, mock_service = client

        mock_service.set_config.return_value = ProvisionSetConfigResult(
            success=True,
            requires_reboot=True,
            changes=["hostname", "reverse_port"],
            message="Configuration updated successfully",
        )

        response = test_client.post(
            "/api/provision/config",
            json={"hostname": "talos000003", "reverse_port": 8622},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["requires_reboot"] is True
        assert set(data["changes"]) == {"hostname", "reverse_port"}

    def test_when_invalid_hostname_length_then_returns_422(self, client):
        """Test Pydantic validation for hostname length"""
        test_client, mock_service = client

        response = test_client.post(
            "/api/provision/config",
            json={"hostname": "short", "reverse_port": 8621},
        )

        # After adding min_length/max_length to Pydantic model, this should be 422
        assert response.status_code == 422

        # Flexible error format checking
        error_data = response.json()
        # Could be {"detail": ...} or {"errors": [...], "message": ...}
        assert "errors" in error_data or "detail" in error_data

    def test_when_invalid_hostname_characters_then_returns_422(self, client):
        """Test Pydantic validation for hostname characters"""
        test_client, mock_service = client

        response = test_client.post(
            "/api/provision/config",
            json={"hostname": "talos-00001", "reverse_port": 8621},  # Contains hyphen
        )

        assert response.status_code == 422

    def test_when_invalid_port_range_then_returns_422(self, client):
        """Test Pydantic validation for port range"""
        test_client, mock_service = client

        response = test_client.post(
            "/api/provision/config",
            json={"hostname": "talos000001", "reverse_port": 1023},
        )

        assert response.status_code == 422

    def test_when_service_validation_error_then_returns_400(self, client):
        """Test service-level validation error"""
        test_client, mock_service = client

        # Configure mock to raise ValueError
        mock_service.set_config.side_effect = ValueError("Hostname must be exactly 11 characters")

        response = test_client.post(
            "/api/provision/config",
            json={"hostname": "talos000001", "reverse_port": 8621},
        )

        assert response.status_code == 400
        error_data = response.json()
        error_msg = error_data.get("detail") or error_data.get("message") or str(error_data)
        assert "11 characters" in error_msg

    def test_when_service_error_then_returns_500(self, client):
        """Test internal error"""
        test_client, mock_service = client

        # Configure mock to raise RuntimeError
        mock_service.set_config.side_effect = RuntimeError("Internal error")

        response = test_client.post(
            "/api/provision/config",
            json={"hostname": "talos000001", "reverse_port": 8621},
        )

        assert response.status_code == 500
        error_data = response.json()
        error_msg = error_data.get("detail") or error_data.get("message") or str(error_data)
        assert "Internal error" in error_msg


class TestTriggerReboot:
    """Test POST /api/provision/reboot endpoint"""

    def test_when_reboot_triggered_then_returns_success(self, client):
        """Test successful reboot trigger"""
        test_client, mock_service = client

        response = test_client.post("/api/provision/reboot")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "initiated" in data["message"]

        # Verify service was called
        mock_service.trigger_reboot.assert_called_once()

    def test_when_reboot_fails_then_returns_500(self, client):
        """Test reboot failure"""
        test_client, mock_service = client

        # Configure mock to raise exception
        mock_service.trigger_reboot.side_effect = RuntimeError("Reboot failed")

        response = test_client.post("/api/provision/reboot")

        assert response.status_code == 500
        error_data = response.json()
        error_msg = error_data.get("detail") or error_data.get("message") or str(error_data)
        assert "Reboot failed" in error_msg


class TestRequestValidation:
    """Test request body validation"""

    def test_when_missing_hostname_then_returns_422(self, client):
        """Test missing required field"""
        test_client, mock_service = client

        response = test_client.post(
            "/api/provision/config",
            json={"reverse_port": 8621},  # Missing hostname
        )

        assert response.status_code == 422
        error = response.json()
        # Support both error formats
        assert "errors" in error or "detail" in error

        # If using custom format, check for field error
        if "errors" in error:
            field_names = [err.get("field") for err in error["errors"]]
            assert any("hostname" in str(field) for field in field_names)

    def test_when_missing_port_then_returns_422(self, client):
        """Test missing required field"""
        test_client, mock_service = client

        response = test_client.post(
            "/api/provision/config",
            json={"hostname": "talos000001"},  # Missing reverse_port
        )

        assert response.status_code == 422
        error = response.json()
        assert "errors" in error or "detail" in error

    def test_when_invalid_json_then_returns_422(self, client):
        """Test invalid JSON format"""
        test_client, mock_service = client

        response = test_client.post(
            "/api/provision/config",
            data="not a json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 422

    def test_when_port_is_invalid_string_then_returns_422(self, client):
        """Test type validation"""
        test_client, mock_service = client

        response = test_client.post(
            "/api/provision/config",
            json={"hostname": "talos000001", "reverse_port": "invalid"},
        )

        assert response.status_code == 422
