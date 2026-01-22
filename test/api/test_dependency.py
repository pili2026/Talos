import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api.app_state import TalosAppState
from api.dependency import get_provision_service
from api.service.provision_service import ProvisionService
from core.schema.system_config_schema import SystemConfig


@pytest.fixture
def app_with_provision_service():
    """Create FastAPI app with ProvisionService in state"""
    app = FastAPI()
    app.state.talos = TalosAppState(unified_mode=False)

    # Mock system_config
    system_config = SystemConfig(
        MONITOR_INTERVAL_SECONDS=1.0,
        REMOTE_ACCESS={"REVERSE_SSH": {"PORT": 8621}},
        PATHS={"STATE_DIR": "/tmp"},
        SUBSCRIBERS={},
    )

    # Initialize ProvisionService
    provision_service = ProvisionService(system_config=system_config)
    app.state.talos.provision_service = provision_service
    app.state.talos.system_config = system_config

    return app


class TestGetProvisionService:
    """Test get_provision_service dependency"""

    def test_when_service_initialized_then_returns_instance(self, app_with_provision_service):
        """Test successful dependency resolution"""
        client = TestClient(app_with_provision_service)

        # CRITICAL: Add response_model=None to prevent FastAPI from trying to validate ProvisionService
        @app_with_provision_service.get("/test", response_model=None)
        def test_endpoint(service: ProvisionService = Depends(get_provision_service)):
            return {"service_class": service.__class__.__name__}

        response = client.get("/test")
        assert response.status_code == 200
        assert response.json()["service_class"] == "ProvisionService"

    def test_when_service_not_initialized_then_raises_runtime_error(self):
        """Test error when service not in app state"""
        app = FastAPI()
        app.state.talos = TalosAppState(unified_mode=False)
        # Deliberately not setting provision_service

        client = TestClient(app, raise_server_exceptions=False)

        @app.get("/test", response_model=None)
        def test_endpoint(service: ProvisionService = Depends(get_provision_service)):
            return {}

        response = client.get("/test")
        assert response.status_code == 500  # Internal server error

    def test_when_multiple_calls_then_returns_same_instance(self, app_with_provision_service):
        """Test singleton behavior"""
        client = TestClient(app_with_provision_service)

        instances = []

        @app_with_provision_service.get("/test", response_model=None)
        def test_endpoint(service: ProvisionService = Depends(get_provision_service)):
            instances.append(id(service))
            return {}

        # Make multiple requests
        client.get("/test")
        client.get("/test")
        client.get("/test")

        # All should be the same instance
        assert len(set(instances)) == 1


class TestProvisionServiceIntegration:
    """Integration tests with actual FastAPI dependency injection"""

    def test_when_used_in_real_endpoint_then_works(self, app_with_provision_service):
        """Test that dependency works in real-world scenario"""
        client = TestClient(app_with_provision_service)

        @app_with_provision_service.get("/config/current", response_model=None)
        def get_current(service: ProvisionService = Depends(get_provision_service)):
            config = service.get_current_config()
            return {
                "hostname": config.hostname,
                "port": config.reverse_port,
            }

        response = client.get("/config/current")
        assert response.status_code == 200
        data = response.json()
        assert "hostname" in data
        assert "port" in data

    def test_when_dependency_chain_then_resolves_correctly(self, app_with_provision_service):
        """Test dependency injection in a chain"""
        client = TestClient(app_with_provision_service)

        def get_config_summary(service: ProvisionService = Depends(get_provision_service)) -> dict:
            """Helper dependency that uses ProvisionService"""
            config = service.get_current_config()
            return {
                "summary": f"{config.hostname}:{config.reverse_port}",
                "source": config.port_source,
            }

        @app_with_provision_service.get("/summary", response_model=None)
        def get_summary(summary: dict = Depends(get_config_summary)):
            return summary

        response = client.get("/summary")
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data
        assert "source" in data
