"""FastAPI Dependency Injection

Centralized management of injectable services and repositories.
"""

from functools import lru_cache

from fastapi import Depends, Request

from api.repository.config_repository import ConfigRepository
from api.service.device_service import DeviceService
from api.service.parameter_service import ParameterService
from api.service.constraint_service import ConstraintService
from api.service.wifi_service import WiFiService
from device_manager import AsyncDeviceManager
from schema.constraint_schema import ConstraintConfigSchema

# ===== Singleton Caches =====


@lru_cache()
def get_config_repository() -> ConfigRepository:
    """Return a singleton ConfigRepository instance."""

    return ConfigRepository()


# ===== Service Layer Dependencies =====


def get_async_device_manager(request: Request) -> AsyncDeviceManager:
    """Provide the shared AsyncDeviceManager stored on the FastAPI app."""

    manager = getattr(request.app.state, "async_device_manager", None)
    if manager is None:
        raise RuntimeError("AsyncDeviceManager is not initialized")
    return manager


def get_device_service(
    device_manager: AsyncDeviceManager = Depends(get_async_device_manager),
    config_repo: ConfigRepository = Depends(get_config_repository),
) -> DeviceService:
    return DeviceService(device_manager, config_repo)


def get_parameter_service(
    device_manager: AsyncDeviceManager = Depends(get_async_device_manager),
    config_repo: ConfigRepository = Depends(get_config_repository),
) -> ParameterService:
    """Resolve ParameterService backed by the shared AsyncDeviceManager."""

    return ParameterService(device_manager, config_repo)


def get_constraint_schema(request: Request) -> ConstraintConfigSchema:
    """Provide the shared ConstraintConfigSchema stored on the FastAPI app."""

    schema = getattr(request.app.state, "constraint_schema", None)
    if schema is None:
        raise RuntimeError("ConstraintConfigSchema is not initialized")
    return schema


def get_constraint_service(
    constraint_schema: ConstraintConfigSchema = Depends(get_constraint_schema),
    config_repo: ConfigRepository = Depends(get_config_repository),
) -> ConstraintService:
    """Resolve ConstraintService with constraint configuration."""

    return ConstraintService(constraint_schema, config_repo)


@lru_cache()
def get_wifi_service() -> WiFiService:
    """Return a singleton WiFiService instance."""

    return WiFiService()
