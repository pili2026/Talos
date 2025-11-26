"""FastAPI Dependency Injection

Centralized management of injectable services and repositories.
"""

import logging
from functools import lru_cache

from fastapi import Depends, Request

from api.repository.config_repository import ConfigRepository
from api.service.constraint_service import ConstraintService
from api.service.device_service import DeviceService
from api.service.parameter_service import ParameterService
from api.service.snapshot_service import SnapshotService
from api.service.wifi_service import WiFiService
from device_manager import AsyncDeviceManager
from repository.snapshot_repository import SnapshotRepository
from schema.constraint_schema import ConstraintConfigSchema
from util.db_manager import SQLiteSnapshotDBManager

logger = logging.getLogger(__name__)


# ===== Singleton Caches =====


@lru_cache()
def get_config_repository() -> ConfigRepository:
    """Return a singleton ConfigRepository instance."""
    return ConfigRepository()


@lru_cache()
def get_wifi_service() -> WiFiService:
    """Return a singleton WiFiService instance."""
    return WiFiService()


# ===== AsyncDeviceManager & Device-related Services =====


def get_async_device_manager(request: Request) -> AsyncDeviceManager:
    """
    Provide the shared AsyncDeviceManager stored on the FastAPI app.

    The app startup code must set:
        app.state.async_device_manager = AsyncDeviceManager(...)
    """
    if not hasattr(request.app.state, "async_device_manager"):
        raise RuntimeError("AsyncDeviceManager is not initialized on app.state")

    manager = request.app.state.async_device_manager
    if manager is None:
        raise RuntimeError("AsyncDeviceManager on app.state is None")

    return manager


def get_device_service(
    device_manager: AsyncDeviceManager = Depends(get_async_device_manager),
    config_repo: ConfigRepository = Depends(get_config_repository),
) -> DeviceService:
    """Resolve DeviceService with AsyncDeviceManager and ConfigRepository."""
    return DeviceService(device_manager, config_repo)


def get_parameter_service(
    device_manager: AsyncDeviceManager = Depends(get_async_device_manager),
    config_repo: ConfigRepository = Depends(get_config_repository),
) -> ParameterService:
    """Resolve ParameterService backed by the shared AsyncDeviceManager."""
    return ParameterService(device_manager, config_repo)


# ===== Constraint Schema & Service =====


def get_constraint_schema(request: Request) -> ConstraintConfigSchema:
    """
    Provide the shared ConstraintConfigSchema stored on the FastAPI app.

    The app startup code must set:
        app.state.constraint_schema = ConstraintConfigSchema(...)
    """
    if not hasattr(request.app.state, "constraint_schema"):
        raise RuntimeError("ConstraintConfigSchema is not initialized on app.state")

    schema = request.app.state.constraint_schema
    if schema is None:
        raise RuntimeError("ConstraintConfigSchema on app.state is None")

    return schema


def get_constraint_service(
    constraint_schema: ConstraintConfigSchema = Depends(get_constraint_schema),
    config_repo: ConfigRepository = Depends(get_config_repository),
) -> ConstraintService:
    """Resolve ConstraintService with constraint configuration."""
    return ConstraintService(constraint_schema, config_repo)


# ===== Snapshot DB / Repository / Service =====


@lru_cache()
def _get_snapshot_db_manager_cached(db_path: str) -> SQLiteSnapshotDBManager:
    """
    Internal cached factory for SQLiteSnapshotDBManager.

    The db_path is used as cache key so different paths produce different instances.
    """
    db_manager = SQLiteSnapshotDBManager(db_path=db_path, echo=False)
    logger.info("[Dependency] Snapshot DB Manager initialized at %s", db_path)
    return db_manager


def get_snapshot_db_manager(request: Request) -> SQLiteSnapshotDBManager:
    """
    Provide SQLiteSnapshotDBManager using app.state.snapshot_db_path.

    The app startup code must set:
        app.state.snapshot_db_path = "/path/to/snapshots.db"
    """
    if not hasattr(request.app.state, "snapshot_db_path"):
        raise RuntimeError("snapshot_db_path is not configured on app.state")

    db_path: str = request.app.state.snapshot_db_path
    if not db_path:
        raise RuntimeError("snapshot_db_path on app.state is empty")

    return _get_snapshot_db_manager_cached(db_path)


@lru_cache()
def _get_snapshot_repository_cached(db_path: str) -> SnapshotRepository:
    """
    Internal cached factory for SnapshotRepository.

    Bound to db_path so tests or multi-db setups can still work.
    """
    db_manager = _get_snapshot_db_manager_cached(db_path)
    return SnapshotRepository(db_manager=db_manager)


def get_snapshot_repository(request: Request) -> SnapshotRepository:
    """
    Provide SnapshotRepository bound to the current snapshot DB path.

    The app startup code must set:
        app.state.snapshot_db_path = "/path/to/snapshots.db"
    """
    if not hasattr(request.app.state, "snapshot_db_path"):
        raise RuntimeError("snapshot_db_path is not configured on app.state")

    db_path: str = request.app.state.snapshot_db_path
    if not db_path:
        raise RuntimeError("snapshot_db_path on app.state is empty")

    return _get_snapshot_repository_cached(db_path)


def get_snapshot_service(
    snapshot_repo: SnapshotRepository = Depends(get_snapshot_repository),
) -> SnapshotService:
    """Resolve SnapshotService with repository dependency."""
    return SnapshotService(snapshot_repo)
