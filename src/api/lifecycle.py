"""Startup and shutdown hooks for the FastAPI application."""

import logging
import os
from pathlib import Path

from fastapi import FastAPI

from api.repository.config_repository import ConfigRepository
from core.schema.constraint_schema import ConstraintConfigSchema
from core.util.config_manager import ConfigManager
from device_manager import AsyncDeviceManager

logger = logging.getLogger(__name__)


async def startup_event(app: FastAPI) -> None:
    """Initialize API service with conditional initialization."""
    logger.info("=" * 60)
    logger.info("Starting Talos API Service...")
    logger.info("=" * 60)

    try:
        # Load config repository
        config_repo = ConfigRepository()
        config_repo.initialize_sync()
        logger.info("Configuration repository loaded")

        # Check deployment mode
        if app.state.talos.is_unified_mode():
            # ========== Unified Mode ==========
            logger.info("=" * 60)
            logger.info("UNIFIED MODE DETECTED")
            logger.info("=" * 60)
            logger.info(f"State: {app.state.talos}")

            # Verify required components
            if app.state.talos.constraint_schema is None:
                raise RuntimeError("constraint_schema not injected")
            if app.state.talos.pubsub is None:
                raise RuntimeError("pubsub not injected")

            logger.info("All shared instances verified")

            # Load snapshot config
            base_res_path = Path(__file__).parent.parent.parent / "res"
            snapshot_config_path = Path(os.getenv("TALOS_SNAPSHOT_CONFIG", base_res_path / "snapshot_storage.yml"))
            snapshot_cfg = ConfigManager.load_yaml_file(str(snapshot_config_path))

            app.state.talos.snapshot_db_path = snapshot_cfg.get("db_path", "./data/snapshots.db")
            app.state.talos.snapshot_config_path = str(snapshot_config_path)

            logger.info(f"Snapshot config loaded (db={app.state.talos.snapshot_db_path})")
            logger.info("=" * 60)
            logger.info("API startup completed (UNIFIED MODE)")
            logger.info("=" * 60)
            return

        # ========== Standalone Mode ==========
        logger.info("=" * 60)
        logger.info("STANDALONE MODE")
        logger.info("=" * 60)
        logger.info("Initializing independent instances")

        base_res_path = Path(__file__).parent.parent.parent / "res"

        instance_config_path = Path(os.getenv("TALOS_INSTANCE_CONFIG", base_res_path / "device_instance_config.yml"))
        modbus_device_path = Path(os.getenv("TALOS_MODBUS_CONFIG", base_res_path / "modbus_device.yml"))

        logger.info(f"Instance config: {instance_config_path}")
        logger.info(f"Modbus config: {modbus_device_path}")

        # Initialize components
        constraint_config = ConfigManager.load_yaml_file(str(instance_config_path))
        constraint_schema = ConstraintConfigSchema(**constraint_config)

        async_device_manager = AsyncDeviceManager(str(modbus_device_path), constraint_schema)
        await async_device_manager.init()

        # Update app state
        app.state.talos.async_device_manager = async_device_manager
        app.state.talos.constraint_schema = constraint_schema
        app.state.talos.unified_mode = False

        logger.info(f"AsyncDeviceManager initialized ({len(async_device_manager.device_list)} devices)")

        # Load snapshot config
        snapshot_config_path = Path(os.getenv("TALOS_SNAPSHOT_CONFIG", base_res_path / "snapshot_storage.yml"))
        snapshot_cfg = ConfigManager.load_yaml_file(str(snapshot_config_path))

        app.state.talos.snapshot_db_path = snapshot_cfg.get("db_path", "./data/snapshots.db")
        app.state.talos.snapshot_config_path = str(snapshot_config_path)

        logger.info("Snapshot config loaded")
        logger.info(f"State: {app.state.talos}")
        logger.info("=" * 60)
        logger.info("API startup completed (STANDALONE MODE)")
        logger.info("=" * 60)

    except Exception as exc:
        logger.error("=" * 60)
        logger.error("STARTUP FAILED")
        logger.error("=" * 60)
        logger.error(f"Error: {exc}", exc_info=True)
        raise


async def shutdown_event(app: FastAPI) -> None:
    """Clean up resources before shutdown."""
    logger.info("=" * 60)
    logger.info("Shutting down Talos API Service...")
    logger.info("=" * 60)

    if app.state.talos.is_unified_mode():
        logger.info("UNIFIED MODE: Cleanup handled by main_with_api.py")
        return

    # Standalone mode: cleanup
    logger.info("STANDALONE MODE: Performing cleanup")

    if app.state.talos.async_device_manager:
        try:
            await app.state.talos.async_device_manager.shutdown()
            logger.info("AsyncDeviceManager shutdown completed")
        except Exception as exc:
            logger.error(f"Error during shutdown: {exc}")

    logger.info("=" * 60)
    logger.info("Shutdown completed")
    logger.info("=" * 60)
