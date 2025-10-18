"""
FastAPI Dependency Injection

Centralized management of all injectable dependencies.
Implements Inversion of Control (IoC).
"""

from functools import lru_cache
from fastapi import Depends
from api.service.device_service import DeviceService
from api.service.parameter_service import ParameterService
from api.repository.modbus_repository import ModbusRepository
from api.repository.config_repository import ConfigRepository


# ===== Singleton Caches =====


@lru_cache()
def get_modbus_repository() -> ModbusRepository:
    """Get a singleton instance of the Modbus Repository"""
    return ModbusRepository()


@lru_cache()
def get_config_repository() -> ConfigRepository:
    """Get a singleton instance of the Config Repository"""
    return ConfigRepository()


# ===== Service Layer Dependencies =====


def get_device_service(
    modbus_repo: ModbusRepository = Depends(get_modbus_repository),
    config_repo: ConfigRepository = Depends(get_config_repository),
) -> DeviceService:
    """
    Get an instance of the DeviceService.

    Args:
        modbus_repo: Data access layer for Modbus operations.
        config_repo: Data access layer for configuration management.

    Returns:
        DeviceService: An initialized DeviceService instance.
    """
    return DeviceService(modbus_repo, config_repo)


def get_parameter_service(
    modbus_repo: ModbusRepository = Depends(get_modbus_repository),
    config_repo: ConfigRepository = Depends(get_config_repository),
) -> ParameterService:
    """
    Get an instance of the ParameterService.

    Args:
        modbus_repo: Data access layer for Modbus operations.
        config_repo: Data access layer for configuration management.

    Returns:
        ParameterService: An initialized ParameterService instance.
    """
    return ParameterService(modbus_repo, config_repo)
