"""
Device Router Tests

Tests for device-related API endpoints:
- GET /api/devices/ (list all devices)
- GET /api/devices/{device_id} (get single device)
- GET /api/devices/{device_id}/connectivity (check connectivity)
"""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.dependency import get_device_service
from api.model.enums import DeviceConnectionStatus, ResponseStatus
from api.model.responses import DeviceInfo


@pytest.fixture
def client():
    """Create FastAPI test client"""
    # Use a fresh client for each test to avoid state issues
    return TestClient(app)


@pytest.fixture
def mock_device_service():
    """Mock DeviceService with common responses"""
    service = AsyncMock()

    # Default device list
    service.get_all_devices.return_value = [
        DeviceInfo(
            device_id="TECO_VFD_1",
            model="TECO_VFD",
            slave_id="1",
            connection_status=DeviceConnectionStatus.UNKNOWN.value,
            available_parameters=["Hz", "KW"],
        ),
        DeviceInfo(
            device_id="SD400_3",
            model="SD400",
            slave_id="3",
            connection_status=DeviceConnectionStatus.UNKNOWN.value,
            available_parameters=["AIn01"],
        ),
    ]

    # Default single device response
    service.get_device_by_id.return_value = DeviceInfo(
        device_id="TECO_VFD_1",
        model="TECO_VFD",
        slave_id="1",
        connection_status=DeviceConnectionStatus.ONLINE.value,
        available_parameters=["Hz", "KW"],
    )

    # Default connectivity check
    service.check_device_connectivity.return_value = DeviceConnectionStatus.ONLINE

    return service


class TestListDevices:
    """Test suite for GET /api/devices/"""

    def test_when_no_query_param_then_should_use_default_include_status_false(self, client, mock_device_service):
        """
        GIVEN no include_status query parameter
        WHEN GET /api/devices/
        THEN should call service with include_status=False (default)
        AND return 200 with device list
        """
        # Override dependency
        app.dependency_overrides[get_device_service] = lambda: mock_device_service

        try:
            # Act
            response = client.get("/api/devices/")

            # Assert
            assert response.status_code == 200
            data = response.json()

            assert data["status"] == ResponseStatus.SUCCESS.value
            assert data["total_count"] == 2
            assert len(data["devices"]) == 2

            # Verify service was called with include_status=False
            mock_device_service.get_all_devices.assert_called_once_with(include_status=False)
        finally:
            # Clean up
            app.dependency_overrides.clear()

    def test_when_include_status_false_then_should_pass_to_service(self, client, mock_device_service):
        """
        GIVEN include_status=false query parameter
        WHEN GET /api/devices/?include_status=false
        THEN should call service with include_status=False
        """
        app.dependency_overrides[get_device_service] = lambda: mock_device_service

        try:
            # Act
            response = client.get("/api/devices/?include_status=false")

            # Assert
            assert response.status_code == 200
            mock_device_service.get_all_devices.assert_called_once_with(include_status=False)
        finally:
            app.dependency_overrides.clear()

    def test_when_include_status_true_then_should_pass_to_service(self, client, mock_device_service):
        """
        GIVEN include_status=true query parameter
        WHEN GET /api/devices/?include_status=true
        THEN should call service with include_status=True
        AND devices should have status information
        """
        # Arrange: Mock devices with actual status
        mock_device_service.get_all_devices.return_value = [
            DeviceInfo(
                device_id="TECO_VFD_1",
                model="TECO_VFD",
                slave_id="1",
                connection_status=DeviceConnectionStatus.ONLINE.value,
                available_parameters=["Hz", "KW"],
            ),
            DeviceInfo(
                device_id="SD400_3",
                model="SD400",
                slave_id="3",
                connection_status=DeviceConnectionStatus.OFFLINE.value,
                available_parameters=["AIn01"],
            ),
        ]

        app.dependency_overrides[get_device_service] = lambda: mock_device_service

        try:
            # Act
            response = client.get("/api/devices/?include_status=true")

            # Assert
            assert response.status_code == 200
            data = response.json()

            assert data["devices"][0]["connection_status"] == DeviceConnectionStatus.ONLINE.value
            assert data["devices"][1]["connection_status"] == DeviceConnectionStatus.OFFLINE.value

            mock_device_service.get_all_devices.assert_called_once_with(include_status=True)
        finally:
            app.dependency_overrides.clear()

    def test_when_devices_exist_then_should_return_correct_response_structure(self, client, mock_device_service):
        """
        GIVEN devices are configured
        WHEN GET /api/devices/
        THEN should return correct response structure with all fields
        """
        app.dependency_overrides[get_device_service] = lambda: mock_device_service

        try:
            # Act
            response = client.get("/api/devices/")

            # Assert
            assert response.status_code == 200
            data = response.json()

            # Check response structure
            assert "status" in data
            assert "devices" in data
            assert "total_count" in data

            # Check device structure
            device = data["devices"][0]
            assert "device_id" in device
            assert "model" in device
            assert "slave_id" in device
            assert "connection_status" in device
            assert "available_parameters" in device
        finally:
            app.dependency_overrides.clear()

    def test_when_no_devices_configured_then_should_return_empty_list(self, client, mock_device_service):
        """
        GIVEN no devices are configured
        WHEN GET /api/devices/
        THEN should return empty list with total_count=0
        """
        # Arrange
        mock_device_service.get_all_devices.return_value = []

        app.dependency_overrides[get_device_service] = lambda: mock_device_service

        try:
            # Act
            response = client.get("/api/devices/")

            # Assert
            assert response.status_code == 200
            data = response.json()

            assert data["status"] == ResponseStatus.SUCCESS.value
            assert data["total_count"] == 0
            assert data["devices"] == []
        finally:
            app.dependency_overrides.clear()

    def test_when_service_raises_exception_then_should_return_500(self, client, mock_device_service):
        """
        GIVEN service raises an exception
        WHEN GET /api/devices/
        THEN should return 500 error
        """
        # Arrange
        mock_device_service.get_all_devices.side_effect = Exception("Database error")

        app.dependency_overrides[get_device_service] = lambda: mock_device_service

        try:
            # Act
            response = client.get("/api/devices/")

            # Assert
            assert response.status_code == 500
        finally:
            app.dependency_overrides.clear()


class TestGetDevice:
    """Test suite for GET /api/devices/{device_id}"""

    def test_when_device_exists_and_no_query_param_then_should_use_default_include_status_true(
        self, client, mock_device_service
    ):
        """
        GIVEN device exists and no include_status parameter
        WHEN GET /api/devices/{device_id}
        THEN should call service with include_status=True (default for single device)
        AND return 200 with device info
        """
        app.dependency_overrides[get_device_service] = lambda: mock_device_service

        try:
            # Act
            response = client.get("/api/devices/TECO_VFD_1")

            # Assert
            assert response.status_code == 200
            data = response.json()

            assert data["device_id"] == "TECO_VFD_1"
            assert data["connection_status"] == DeviceConnectionStatus.ONLINE.value

            mock_device_service.get_device_by_id.assert_called_once_with("TECO_VFD_1", include_status=True)
        finally:
            app.dependency_overrides.clear()

    def test_when_include_status_false_then_should_pass_to_service(self, client, mock_device_service):
        """
        GIVEN include_status=false query parameter
        WHEN GET /api/devices/{device_id}?include_status=false
        THEN should call service with include_status=False
        AND return device without status check
        """
        # Arrange
        mock_device_service.get_device_by_id.return_value = DeviceInfo(
            device_id="TECO_VFD_1",
            model="TECO_VFD",
            slave_id="1",
            connection_status=DeviceConnectionStatus.UNKNOWN.value,
            available_parameters=["Hz", "KW"],
        )

        app.dependency_overrides[get_device_service] = lambda: mock_device_service

        try:
            # Act
            response = client.get("/api/devices/TECO_VFD_1?include_status=false")

            # Assert
            assert response.status_code == 200
            data = response.json()

            assert data["connection_status"] == DeviceConnectionStatus.UNKNOWN.value
            mock_device_service.get_device_by_id.assert_called_once_with("TECO_VFD_1", include_status=False)
        finally:
            app.dependency_overrides.clear()

    def test_when_include_status_true_then_should_pass_to_service(self, client, mock_device_service):
        """
        GIVEN include_status=true query parameter
        WHEN GET /api/devices/{device_id}?include_status=true
        THEN should call service with include_status=True
        """
        app.dependency_overrides[get_device_service] = lambda: mock_device_service

        try:
            # Act
            response = client.get("/api/devices/SD400_3?include_status=true")

            # Assert
            assert response.status_code == 200
            mock_device_service.get_device_by_id.assert_called_once_with("SD400_3", include_status=True)
        finally:
            app.dependency_overrides.clear()

    def test_when_device_not_found_then_should_return_404(self, client, mock_device_service):
        """
        GIVEN device does not exist
        WHEN GET /api/devices/{device_id}
        THEN should return 404 with error message
        """
        # Arrange
        mock_device_service.get_device_by_id.return_value = None

        app.dependency_overrides[get_device_service] = lambda: mock_device_service

        try:
            # Act
            response = client.get("/api/devices/NOT_EXIST")

            # Assert
            assert response.status_code == 404
            data = response.json()
            assert "detail" in data
            assert "NOT_EXIST" in data["detail"]
        finally:
            app.dependency_overrides.clear()

    def test_when_device_exists_then_should_return_correct_structure(self, client, mock_device_service):
        """
        GIVEN device exists
        WHEN GET /api/devices/{device_id}
        THEN should return device info with all fields
        """
        app.dependency_overrides[get_device_service] = lambda: mock_device_service

        try:
            # Act
            response = client.get("/api/devices/TECO_VFD_1")

            # Assert
            assert response.status_code == 200
            data = response.json()

            assert data["device_id"] == "TECO_VFD_1"
            assert data["model"] == "TECO_VFD"
            assert data["slave_id"] == "1"
            assert "connection_status" in data
            assert "available_parameters" in data
        finally:
            app.dependency_overrides.clear()

    def test_when_service_raises_exception_then_should_return_500(self, client, mock_device_service):
        """
        GIVEN service raises an exception
        WHEN GET /api/devices/{device_id}
        THEN should return 500 error
        """
        # Arrange
        mock_device_service.get_device_by_id.side_effect = Exception("Modbus error")

        app.dependency_overrides[get_device_service] = lambda: mock_device_service

        try:
            # Act
            response = client.get("/api/devices/TECO_VFD_1")

            # Assert
            assert response.status_code == 500
        finally:
            app.dependency_overrides.clear()


class TestCheckConnectivity:
    """Test suite for GET /api/devices/{device_id}/connectivity"""

    def test_when_device_online_then_should_return_online_status(self, client, mock_device_service):
        """
        GIVEN device is online
        WHEN GET /api/devices/{device_id}/connectivity
        THEN should return online status with is_online=true
        """
        # Arrange
        mock_device_service.check_device_connectivity.return_value = DeviceConnectionStatus.ONLINE

        app.dependency_overrides[get_device_service] = lambda: mock_device_service

        try:
            # Act
            response = client.get("/api/devices/TECO_VFD_1/connectivity")

            # Assert
            assert response.status_code == 200
            data = response.json()

            assert data["device_id"] == "TECO_VFD_1"
            assert data["connection_status"] == DeviceConnectionStatus.ONLINE.value
            assert data["is_online"] is True
        finally:
            app.dependency_overrides.clear()

    def test_when_device_offline_then_should_return_offline_status(self, client, mock_device_service):
        """
        GIVEN device is offline
        WHEN GET /api/devices/{device_id}/connectivity
        THEN should return offline status with is_online=false
        """
        # Arrange
        mock_device_service.check_device_connectivity.return_value = DeviceConnectionStatus.OFFLINE

        app.dependency_overrides[get_device_service] = lambda: mock_device_service

        try:
            # Act
            response = client.get("/api/devices/SD400_3/connectivity")

            # Assert
            assert response.status_code == 200
            data = response.json()

            assert data["device_id"] == "SD400_3"
            assert data["connection_status"] == DeviceConnectionStatus.OFFLINE.value
            assert data["is_online"] is False
        finally:
            app.dependency_overrides.clear()

    def test_when_connectivity_check_error_then_should_return_error_status(self, client, mock_device_service):
        """
        GIVEN connectivity check encounters an error
        WHEN GET /api/devices/{device_id}/connectivity
        THEN should return error status with is_online=false
        """
        # Arrange
        mock_device_service.check_device_connectivity.return_value = DeviceConnectionStatus.ERROR

        app.dependency_overrides[get_device_service] = lambda: mock_device_service

        try:
            # Act
            response = client.get("/api/devices/ADAM_4117_12/connectivity")

            # Assert
            assert response.status_code == 200
            data = response.json()

            assert data["device_id"] == "ADAM_4117_12"
            assert data["connection_status"] == DeviceConnectionStatus.ERROR.value
            assert data["is_online"] is False
        finally:
            app.dependency_overrides.clear()

    def test_when_service_raises_exception_then_should_return_500(self, client, mock_device_service):
        """
        GIVEN service raises an exception
        WHEN GET /api/devices/{device_id}/connectivity
        THEN should return 500 error
        """
        # Arrange
        mock_device_service.check_device_connectivity.side_effect = Exception("Connection timeout")

        app.dependency_overrides[get_device_service] = lambda: mock_device_service

        try:
            # Act
            response = client.get("/api/devices/TECO_VFD_1/connectivity")

            # Assert
            assert response.status_code == 500
        finally:
            app.dependency_overrides.clear()


class TestEndpointIntegration:
    """Integration tests for endpoint behavior"""

    def test_when_listing_devices_without_status_then_getting_single_device_with_status(
        self, client, mock_device_service
    ):
        """
        Simulate real-world workflow:
        1. List all devices without status (fast)
        2. Get single device with status (detailed)
        """
        app.dependency_overrides[get_device_service] = lambda: mock_device_service

        try:
            # Step 1: List devices without status
            list_response = client.get("/api/devices/?include_status=false")
            assert list_response.status_code == 200
            mock_device_service.get_all_devices.assert_called_once_with(include_status=False)

            # Step 2: Get specific device with status
            device_response = client.get("/api/devices/TECO_VFD_1?include_status=true")
            assert device_response.status_code == 200
            mock_device_service.get_device_by_id.assert_called_once_with("TECO_VFD_1", include_status=True)
        finally:
            app.dependency_overrides.clear()

    def test_response_headers_and_content_type(self, client, mock_device_service):
        """
        GIVEN valid requests
        WHEN calling any device endpoint
        THEN should return correct content-type
        """
        app.dependency_overrides[get_device_service] = lambda: mock_device_service

        try:
            response = client.get("/api/devices/")

            assert response.status_code == 200
            assert response.headers["content-type"] == "application/json"
        finally:
            app.dependency_overrides.clear()
