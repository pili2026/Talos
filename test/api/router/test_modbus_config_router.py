"""
API Integration Tests for Configuration Management
Tests the complete API stack (router -> service -> yaml_manager)
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.app_state import TalosAppState
from api.router import modbus_config
from core.schema.modbus_config_metadata import ConfigSource
from core.schema.modbus_device_schema import ModbusBusConfig, ModbusDeviceConfig, ModbusDeviceFileConfig
from core.util.config_manager import ConfigManager
from core.util.yaml_manager import YAMLManager


@pytest.fixture
def temp_config_dir(tmp_path):
    """Create temporary config directory"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def yaml_manager(temp_config_dir):
    """Create YAMLManager"""
    return YAMLManager(temp_config_dir, backup_count=5)


@pytest.fixture
def initialized_config(yaml_manager):
    """Initialize config file"""
    config = ModbusDeviceFileConfig(
        bus_dict={"rtu0": ModbusBusConfig(port="/dev/ttyUSB0", baudrate=9600, timeout=1.0)},
        device_list=[
            ModbusDeviceConfig(
                model="TECO_VFD", type="vfd", model_file="driver/teco_vfd.yml", slave_id=1, bus="rtu0", modes={}
            )
        ],
    )

    yaml_manager.update_config("modbus_device", config, config_source=ConfigSource.MANUAL, modified_by="test_fixture")

    return config


@pytest.fixture
def app(yaml_manager):
    """Create FastAPI app with test dependencies"""

    app = FastAPI()
    app.state.talos = TalosAppState()
    app.state.talos.yaml_manager = yaml_manager
    app.state.talos.config_manager = ConfigManager(yaml_manager=yaml_manager)

    app.include_router(modbus_config.router, prefix="/api/config/modbus")
    return app


@pytest.fixture
def client(app):
    """Create test client"""
    return TestClient(app)


class TestMetadataEndpoints:
    """Test /api/config/modbus/metadata"""

    def test_given_existing_config_when_getting_metadata_then_success_and_metadata_are_returned(
        self, client, initialized_config
    ):
        """Test GET /metadata"""
        response = client.get("/api/config/modbus/metadata")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "success"
        assert "metadata" in data
        assert data["metadata"]["generation"] >= 1
        assert "checksum" in data["metadata"]

    def test_given_no_config_file_when_getting_metadata_then_not_found_is_returned(self, client):
        """Test GET /metadata when file doesn't exist"""
        response = client.get("/api/config/modbus/metadata")

        assert response.status_code == 404


class TestConfigEndpoints:
    """Test /api/config/modbus"""

    def test_given_existing_config_when_getting_config_then_full_config_is_returned(self, client, initialized_config):
        """Test GET /api/config/modbus"""
        response = client.get("/api/config/modbus")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "success"
        assert "metadata" in data
        assert "buses" in data
        assert "devices" in data

        assert "rtu0" in data["buses"]
        assert len(data["devices"]) == 1
        assert data["devices"][0]["model"] == "TECO_VFD"


class TestBusEndpoints:
    """Test /api/config/modbus/buses"""

    def test_given_new_bus_payload_when_creating_bus_then_success_and_generation_increases(
        self, client, initialized_config
    ):
        """Test POST /buses/{bus_name}"""
        response = client.post(
            "/api/config/modbus/buses/rtu1",
            json={"port": "/dev/ttyUSB1", "baudrate": 19200, "timeout": 1.5},
            headers={"X-User-Email": "test@example.com"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "success"
        assert "generation" in data
        assert data["generation"] >= 2

    def test_given_bus_is_in_use_when_deleting_bus_then_conflict_is_returned(self, client, initialized_config):
        """Test DELETE /buses/{bus_name} when in use"""
        response = client.delete("/api/config/modbus/buses/rtu0", headers={"X-User-Email": "test@example.com"})

        assert response.status_code == 409
        assert "in use" in response.json()["detail"].lower()

    def test_given_bus_does_not_exist_when_deleting_bus_then_not_found_is_returned(self, client, initialized_config):
        """Test DELETE /buses/{bus_name} when doesn't exist"""
        response = client.delete("/api/config/modbus/buses/nonexistent", headers={"X-User-Email": "test@example.com"})

        assert response.status_code == 404


class TestDeviceEndpoints:
    """Test /api/config/modbus/devices"""

    def test_given_valid_device_payload_when_creating_device_then_device_is_created(self, client, initialized_config):
        """Test POST /devices"""
        response = client.post(
            "/api/config/modbus/devices",
            json={
                "model": "ADAM_4117",
                "type": "analog_input",
                "model_file": "driver/adam_4117.yml",
                "slave_id": 2,
                "bus": "rtu0",
                "modes": {},
            },
            headers={"X-User-Email": "test@example.com"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "success"
        assert "created" in data["message"].lower()

    def test_given_invalid_bus_in_device_payload_when_creating_device_then_bad_request_is_returned(
        self, client, initialized_config
    ):
        """Test POST /devices with invalid bus"""
        response = client.post(
            "/api/config/modbus/devices",
            json={
                "model": "TEST",
                "type": "test",
                "model_file": "test.yml",
                "slave_id": 99,
                "bus": "invalid_bus",
                "modes": {},
            },
            headers={"X-User-Email": "test@example.com"},
        )

        assert response.status_code == 400

    def test_given_existing_device_payload_when_posting_device_then_device_is_updated(self, client, initialized_config):
        """Test POST /devices to update existing"""
        response = client.post(
            "/api/config/modbus/devices",
            json={
                "model": "TECO_VFD",
                "type": "vfd",
                "model_file": "driver/teco_vfd_v2.yml",
                "slave_id": 1,
                "bus": "rtu0",
                "modes": {"special": True},
            },
            headers={"X-User-Email": "test@example.com"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "updated" in data["message"].lower()

    def test_given_existing_device_when_deleting_device_then_device_is_deleted(self, client, initialized_config):
        """Test DELETE /devices/{model}/{slave_id}"""
        response = client.delete("/api/config/modbus/devices/TECO_VFD/1", headers={"X-User-Email": "test@example.com"})

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "success"
        assert "deleted" in data["message"].lower()

    def test_given_device_does_not_exist_when_deleting_device_then_not_found_is_returned(
        self, client, initialized_config
    ):
        """Test DELETE /devices/{model}/{slave_id} when doesn't exist"""
        response = client.delete(
            "/api/config/modbus/devices/NONEXISTENT/999", headers={"X-User-Email": "test@example.com"}
        )

        assert response.status_code == 404


class TestBackupEndpoints:
    """Test /api/config/modbus/backups"""

    def test_given_config_is_updated_when_listing_backups_then_backups_are_returned(self, client, initialized_config):
        """Test GET /backups"""
        # Make a change to create backup
        client.post(
            "/api/config/modbus/buses/rtu1",
            json={"port": "/dev/ttyUSB1", "baudrate": 9600, "timeout": 1.0},
            headers={"X-User-Email": "test@example.com"},
        )

        response = client.get("/api/config/modbus/backups")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "success"
        assert "backups" in data
        assert data["total"] >= 1

    def test_given_backup_exists_when_restoring_backup_then_restore_succeeds(
        self, client, initialized_config, yaml_manager
    ):
        """Test POST /backups/{filename}/restore"""
        # Make changes to create backups
        client.post(
            "/api/config/modbus/buses/rtu1",
            json={"port": "/dev/ttyUSB1", "baudrate": 9600, "timeout": 1.0},
            headers={"X-User-Email": "test@example.com"},
        )

        # Get backup list
        backups_response = client.get("/api/config/modbus/backups")
        backups = backups_response.json()["backups"]

        if backups:
            filename = backups[0]["filename"]

            response = client.post(
                f"/api/config/modbus/backups/{filename}/restore", headers={"X-User-Email": "test@example.com"}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"


class TestUserTracking:
    """Test user tracking in requests"""

    def test_given_user_email_header_when_updating_config_then_last_modified_by_is_set(
        self, client, initialized_config
    ):
        """Test that user email is captured from header"""
        response = client.post(
            "/api/config/modbus/buses/rtu1",
            json={"port": "/dev/ttyUSB1", "baudrate": 9600, "timeout": 1.0},
            headers={"X-User-Email": "jeremy@example.com"},
        )

        assert response.status_code == 200

        # Check metadata
        metadata_response = client.get("/api/config/modbus/metadata")
        metadata = metadata_response.json()["metadata"]

        assert metadata["last_modified_by"] == "jeremy@example.com"

    def test_given_no_user_email_header_when_updating_config_then_last_modified_by_defaults_to_system(
        self, client, initialized_config
    ):
        """Test default user is 'system' when header not provided"""
        response = client.post(
            "/api/config/modbus/buses/rtu1", json={"port": "/dev/ttyUSB1", "baudrate": 9600, "timeout": 1.0}
        )

        assert response.status_code == 200

        # Check metadata
        metadata_response = client.get("/api/config/modbus/metadata")
        metadata = metadata_response.json()["metadata"]

        assert metadata["last_modified_by"] == "system"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
