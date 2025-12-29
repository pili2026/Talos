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
from core.schema.constraint_schema import ConstraintConfigSchema
from core.util.device_health_manager import DeviceHealthManager
from core.util.pubsub.base import PubSub
from device_manager import AsyncDeviceManager
from repository.snapshot_repository import SnapshotRepository
from repository.util.db_manager import SQLiteSnapshotDBManager

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
    """Provide AsyncDeviceManager from app state."""
    return request.app.state.talos.get_device_manager()


def get_health_manager(request: Request) -> DeviceHealthManager:
    """Provide DeviceHealthManager from app state (unified mode only)."""
    return request.app.state.talos.get_health_manager()


def get_device_service(
    device_manager: AsyncDeviceManager = Depends(get_async_device_manager),
    config_repo: ConfigRepository = Depends(get_config_repository),
    health_manager: DeviceHealthManager = Depends(get_health_manager),
) -> DeviceService:
    """Resolve DeviceService with AsyncDeviceManager and ConfigRepository."""
    return DeviceService(device_manager, config_repo, health_manager)


def get_parameter_service(
    device_manager: AsyncDeviceManager = Depends(get_async_device_manager),
    config_repo: ConfigRepository = Depends(get_config_repository),
) -> ParameterService:
    """Resolve ParameterService backed by the shared AsyncDeviceManager."""
    return ParameterService(device_manager, config_repo)


# ===== Constraint Schema & Service =====


def get_constraint_schema(request: Request) -> ConstraintConfigSchema:
    """Provide ConstraintConfigSchema from app state."""
    return request.app.state.talos.get_constraint_schema()


def get_pubsub(request: Request) -> PubSub:
    """
    Provide PubSub instance (unified mode only).

    Raises:
        RuntimeError: If not in unified mode
    """
    return request.app.state.talos.get_pubsub()


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
    """Provide SQLiteSnapshotDBManager."""
    if request.app.state.talos.snapshot_db_path is None:
        raise RuntimeError("Snapshot DB path not configured")

    db_path = request.app.state.talos.snapshot_db_path
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
    if not hasattr(request.app.state.talos, "snapshot_db_path"):
        raise RuntimeError("snapshot_db_path is not configured on app.state")

    db_path: str = request.app.state.talos.snapshot_db_path
    if not db_path:
        raise RuntimeError("snapshot_db_path on app.state is empty")

    return _get_snapshot_repository_cached(db_path)


def get_snapshot_service(
    snapshot_repo: SnapshotRepository = Depends(get_snapshot_repository),
) -> SnapshotService:
    """Resolve SnapshotService with repository dependency."""
    return SnapshotService(snapshot_repo)
