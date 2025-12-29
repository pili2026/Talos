"""
Talos FastAPI Application State

Centralized state management with type safety and runtime validation.
"""

from pydantic import BaseModel, Field, model_validator

from core.schema.constraint_schema import ConstraintConfigSchema
from core.util.device_health_manager import DeviceHealthManager
from core.util.pubsub.base import PubSub
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

    # Snapshot storage
    snapshot_db_path: str | None = Field(default=None, description="Path to SQLite snapshot database")

    snapshot_config_path: str | None = Field(default=None, description="Path to snapshot storage config file")

    # Deployment mode flag
    unified_mode: bool = Field(default=False, description="True if running in unified mode (Core + API)")

    class Config:
        """Pydantic configuration."""

        arbitrary_types_allowed = True  # Allow AsyncDeviceManager, PubSub types
        validate_assignment = True  # Validate on assignment
        extra = "forbid"  # Forbid extra fields

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

    def __repr__(self) -> str:
        """String representation for logging."""
        mode = "unified" if self.is_unified_mode() else "standalone"
        device_count = self.get_device_count()
        pubsub_status = "OK" if self.pubsub else "NO"

        return f"TalosAppState(mode={mode}, " f"devices={device_count}, " f"pubsub={pubsub_status})"
