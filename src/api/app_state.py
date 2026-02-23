"""
Talos FastAPI Application State

Centralized state management with type safety and runtime validation.
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.service.instance_config_service import InstanceConfigService
from api.service.provision_service import ProvisionService
from api.service.system_config_service import SystemConfigService
from api.service.wifi_service import WiFiService
from core.schema.constraint_schema import ConstraintConfigSchema
from core.schema.system_config_schema import SystemConfig
from core.util.config_manager import ConfigManager
from core.util.device_health_manager import DeviceHealthManager
from core.util.pubsub.base import PubSub
from core.util.yaml_manager import YAMLManager
from device_manager import AsyncDeviceManager


class TalosAppState(BaseModel):
    """
    Talos application state container.

    This class defines all shared state in the FastAPI application.
    State is initialized differently based on deployment mode:

    - Unified mode (main_service.py):
      All components are initialized by Core and injected here.

    - Standalone mode (uvicorn api.app:app):
      Components are initialized by lifecycle.py.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True, extra="forbid")

    # Core components
    async_device_manager: AsyncDeviceManager | None = Field(
        default=None, description="Shared Modbus device manager instance"
    )
    pubsub: PubSub | None = Field(
        default=None, description="Message bus for Core/API communication (unified mode only)"
    )
    constraint_schema: ConstraintConfigSchema | None = Field(
        default=None, description="Device constraint configuration"
    )
    health_manager: DeviceHealthManager | None = None

    system_config: SystemConfig | None = None

    yaml_manager: YAMLManager | None = Field(
        default=None, description="YAML configuration manager with version control and backup"
    )
    config_manager: ConfigManager | None = Field(
        default=None, description="Configuration manager supporting both legacy and managed modes"
    )

    # System services
    wifi_service: object | None = Field(default=None, description="WiFi management service with auto-fallback monitor")
    provision_service: object | None = Field(
        default=None, description="System provisioning service (hostname, reverse SSH port)"
    )
    system_config_service: object | None = Field(default=None, description="System config management service")

    instance_config_service: object | None = Field(default=None, description="Instance config management service")

    # Snapshot storage
    snapshot_db_path: str | None = Field(default=None, description="Path to SQLite snapshot database")
    snapshot_config_path: str | None = Field(default=None, description="Path to snapshot storage config file")

    # Deployment mode flag
    unified_mode: bool = Field(default=False, description="True if running in unified mode (Core + API)")

    # Heartbeat
    heartbeat_path: str | None = None
    heartbeat_max_age_sec: float = 60.0

    @model_validator(mode="after")
    def validate_unified_mode_requirements(self) -> "TalosAppState":
        """Validate that unified mode has all required components."""
        if self.unified_mode:
            if self.async_device_manager is None:
                raise ValueError("async_device_manager is required in unified mode")
            if self.constraint_schema is None:
                raise ValueError("constraint_schema is required in unified mode")
        return self

    def is_unified_mode(self) -> bool:
        """Check if running in unified mode."""
        return self.unified_mode and self.async_device_manager is not None

    def is_standalone_mode(self) -> bool:
        """Check if running in standalone mode."""
        return not self.is_unified_mode()

    def require_unified_mode(self, feature: str = "This feature") -> None:
        """
        Raise error if not in unified mode.

        Args:
            feature: Feature name for error message

        Raises:
            RuntimeError: If not in unified mode
        """
        if not self.is_unified_mode():
            raise RuntimeError(
                f"{feature} requires unified mode. " f"Start with main_service.py instead of standalone API."
            )

    def get_pubsub(self) -> PubSub:
        """Get PubSub instance (unified mode only)."""
        self.require_unified_mode("PubSub")
        if self.pubsub is None:
            raise RuntimeError("PubSub is None")
        return self.pubsub

    def get_device_manager(self) -> AsyncDeviceManager:
        """Get AsyncDeviceManager instance."""
        if self.async_device_manager is None:
            raise RuntimeError("AsyncDeviceManager not initialized")
        return self.async_device_manager

    def get_constraint_schema(self) -> ConstraintConfigSchema:
        """Get ConstraintConfigSchema instance."""
        if self.constraint_schema is None:
            raise RuntimeError("ConstraintConfigSchema not initialized")
        return self.constraint_schema

    def get_device_count(self) -> int:
        """Get number of registered devices."""
        if self.async_device_manager is None:
            return 0
        return len(self.async_device_manager.device_list)

    def get_health_manager(self) -> DeviceHealthManager:
        """Get health manager instance (unified mode only)."""
        if not self.unified_mode:
            raise RuntimeError("Health manager only available in unified mode")
        if self.health_manager is None:
            raise RuntimeError("DeviceHealthManager not initialized")
        return self.health_manager

    def get_wifi_service(self) -> WiFiService:
        """Get WiFi service instance."""
        if self.wifi_service is None:
            raise RuntimeError("WiFiService not initialized")
        return self.wifi_service

    def get_provision_service(self) -> ProvisionService:
        """Get ProvisionService instance."""
        if self.provision_service is None:
            raise RuntimeError("ProvisionService not initialized")
        return self.provision_service

    def get_system_config(self) -> SystemConfig:
        """Get SystemConfig instance."""
        if self.system_config is None:
            raise RuntimeError("SystemConfig not initialized")
        return self.system_config

    def get_yaml_manager(self) -> YAMLManager:
        """
        Get YAMLManager instance.

        Returns:
            YAMLManager instance with version control and backup support

        Raises:
            RuntimeError: If YAMLManager not initialized
        """
        if self.yaml_manager is None:
            raise RuntimeError("YAMLManager not initialized")
        return self.yaml_manager

    def get_config_manager(self) -> ConfigManager:
        """
        Get ConfigManager instance.

        Returns:
            ConfigManager instance supporting both legacy and managed modes

        Raises:
            RuntimeError: If ConfigManager not initialized
        """
        if self.config_manager is None:
            raise RuntimeError("ConfigManager not initialized")
        return self.config_manager

    def get_system_config_service(self) -> SystemConfigService:
        if self.system_config_service is None:
            raise RuntimeError("SystemConfigService not initialized")
        return self.system_config_service

    def get_instance_config_service(self) -> InstanceConfigService:
        if self.instance_config_service is None:
            raise RuntimeError("InstanceConfigService not initialized")
        return self.instance_config_service

    def __repr__(self) -> str:
        """String representation for logging."""
        mode = "unified" if self.is_unified_mode() else "standalone"
        device_count = self.get_device_count()
        pubsub_status = "OK" if self.pubsub else "NO"
        wifi_status = "OK" if self.wifi_service else "NO"
        provision_status = "OK" if self.provision_service else "NO"
        yaml_mgr_status = "OK" if self.yaml_manager else "NO"
        config_mgr_status = "OK" if self.config_manager else "NO"
        system_config_service_status = "OK" if self.system_config_service else "NO"
        instance_config_service_status = "OK" if self.instance_config_service else "NO"

        return (
            f"TalosAppState(mode={mode}, "
            f"devices={device_count}, "
            f"pubsub={pubsub_status}, "
            f"wifi={wifi_status}, "
            f"provision={provision_status}, "
            f"yaml_mgr={yaml_mgr_status}, "
            f"config_mgr={config_mgr_status}),"
            f"system_config_service={system_config_service_status}),"
            f"instance_config_service={instance_config_service_status})"
        )
