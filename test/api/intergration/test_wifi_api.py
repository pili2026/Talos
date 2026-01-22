from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from api.dependency import get_wifi_service
from api.model.enums import ResponseStatus
from api.model.wifi import (
    WiFiConnectResponse,
    WiFiInterfaceInfo,
    WiFiInterfacesResponse,
    WiFiListResponse,
    WiFiStatusInfo,
    WiFiStatusResponse,
)
from api.router.wifi import router


@pytest.fixture
def mock_wifi_service():
    """Create a mock WiFi service."""
    return AsyncMock()


@pytest.fixture
def app(mock_wifi_service):
    """Create a FastAPI application with mocked dependencies."""
    app = FastAPI()
    app.include_router(router, prefix="/api/wifi")

    # Override the dependency
    app.dependency_overrides[get_wifi_service] = lambda: mock_wifi_service

    yield app

    # Cleanup
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app: FastAPI):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestWiFiInterfacesEndpoint:
    """Tests for the /api/wifi/interfaces endpoint."""

    @pytest.mark.asyncio
    async def test_get_interfaces_success(self, client, mock_wifi_service):
        """Test: successfully retrieves the interface list."""
        mock_wifi_service.list_interfaces.return_value = WiFiInterfacesResponse(
            status=ResponseStatus.SUCCESS,
            interfaces=[],
            total_count=0,
            recommended_ifname=None,
        )

        response = await client.get("/api/wifi/interfaces")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        mock_wifi_service.list_interfaces.assert_called_once()


class TestWiFiStatusEndpoint:
    """Tests for the /api/wifi/status endpoint."""

    @pytest.mark.asyncio
    async def test_get_status_without_ifname(self, client, mock_wifi_service):
        """Test: retrieves status without specifying ifname."""
        mock_wifi_service.get_status.return_value = WiFiStatusResponse(
            status=ResponseStatus.SUCCESS,
            status_info=WiFiStatusInfo(
                interface="wlan0",
                ssid="TestNetwork",
                bssid="00:11:22:33:44:55",
                freq=None,
                wpa_state="COMPLETED",
                ip_address="192.168.1.100",
                network_id=0,
                key_mgmt=None,
                is_connected=True,
            ),
        )

        response = await client.get("/api/wifi/status")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["status_info"]["interface"] == "wlan0"
        assert data["status_info"]["ssid"] == "TestNetwork"
        assert data["status_info"]["ip_address"] == "192.168.1.100"
        assert data["status_info"]["is_connected"] is True
        mock_wifi_service.get_status.assert_called_once_with(ifname=None)

    @pytest.mark.asyncio
    async def test_get_status_with_ifname(self, client, mock_wifi_service):
        """Test: retrieves status when ifname is specified."""
        mock_wifi_service.get_status.return_value = WiFiStatusResponse(
            status=ResponseStatus.SUCCESS,
            status_info=WiFiStatusInfo(
                interface="wlan1",
                ssid="TestNetwork",
                bssid=None,
                freq=None,
                wpa_state="COMPLETED",
                ip_address="192.168.1.101",
                network_id=1,
                key_mgmt=None,
                is_connected=True,
            ),
        )

        response = await client.get("/api/wifi/status?ifname=wlan1")

        assert response.status_code == 200
        mock_wifi_service.get_status.assert_called_once_with(ifname="wlan1")


class TestWiFiScanEndpoint:
    """Tests for the /api/wifi/scan endpoint."""

    @pytest.mark.asyncio
    async def test_scan_with_default_params(self, client, mock_wifi_service):
        """Test: scan with default parameters."""
        mock_wifi_service.scan.return_value = WiFiListResponse(
            status=ResponseStatus.SUCCESS,
            interface="wlan0",
            networks=[],
            total_count=0,
            current_ssid=None,
        )

        response = await client.get("/api/wifi/scan")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["interface"] == "wlan0"
        assert data["total_count"] == 0
        mock_wifi_service.scan.assert_called_once_with(ifname=None, group_by_ssid=True)

    @pytest.mark.asyncio
    async def test_scan_with_group_by_ssid_false(self, client, mock_wifi_service):
        """Test: scan with group_by_ssid=false."""
        mock_wifi_service.scan.return_value = WiFiListResponse(
            status=ResponseStatus.SUCCESS,
            interface="wlan0",
            networks=[],
            total_count=0,
            current_ssid=None,
        )

        response = await client.get("/api/wifi/scan?group_by_ssid=false")

        assert response.status_code == 200
        mock_wifi_service.scan.assert_called_once_with(ifname=None, group_by_ssid=False)


class TestWiFiConnectEndpoint:
    """Tests for the /api/wifi/connect endpoint."""

    @pytest.mark.asyncio
    async def test_connect_with_valid_request(self, client, mock_wifi_service):
        """Test: valid connect request."""
        mock_wifi_service.connect.return_value = WiFiConnectResponse(
            status=ResponseStatus.SUCCESS,
            interface="wlan0",
            ssid="MyNetwork",
            accepted=True,
            applied_network_id=0,
            applied_priority=4,
            rescue_present=True,
            saved=True,
        )

        payload = {
            "ssid": "MyNetwork",
            "security": "WPA2",
            "psk": "password123",
            "save_config": True,
        }

        response = await client.post("/api/wifi/connect", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] is True
        assert data["ssid"] == "MyNetwork"

    @pytest.mark.asyncio
    async def test_connect_with_missing_required_field_then_422(self, client, mock_wifi_service):
        """Test: returns 422 for missing required fields (Pydantic validation)."""
        # Missing 'ssid' field - should trigger Pydantic validation error
        payload = {
            "security": "WPA2",
            "psk": "password123",
        }

        response = await client.post("/api/wifi/connect", json=payload)

        # Pydantic validation should reject it with 422
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data
        # Verify that the error is about the missing 'ssid' field
        assert any("ssid" in str(error).lower() for error in data["detail"])

    @pytest.mark.asyncio
    async def test_connect_with_invalid_ssid_type_then_422(self, client, mock_wifi_service):
        """Test: returns 422 for invalid field type (Pydantic validation)."""
        # SSID should be string, not integer
        payload = {
            "ssid": 12345,  # Invalid type
            "security": "WPA2",
            "psk": "password123",
        }

        response = await client.post("/api/wifi/connect", json=payload)

        # Pydantic validation should reject it with 422
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_connect_with_too_short_ssid_then_422(self, client, mock_wifi_service):
        """Test: returns 422 for SSID that's too short (Pydantic validation)."""
        # SSID must be at least 1 character according to the model
        payload = {
            "ssid": "",  # Empty string
            "security": "OPEN",
        }

        response = await client.post("/api/wifi/connect", json=payload)

        # Pydantic validation should reject it with 422
        assert response.status_code == 422
