"""Startup and shutdown hooks for the FastAPI application."""

import logging
import os
from pathlib import Path
from fastapi import FastAPI

from api.repository.config_repository import ConfigRepository
from device_manager import AsyncDeviceManager
from schema.constraint_schema import ConstraintConfigSchema
from util.config_manager import ConfigManager

logger = logging.getLogger(__name__)


async def startup_event(app: FastAPI) -> None:
    logger.info("Starting Talos API Service...")

    try:
        # 1. Load configs
        config_repo = ConfigRepository()
        config_repo.initialize_sync()
        logger.info("Configuration loaded successfully")

        # 2. Resolve config paths (支援環境變數覆蓋)
        base_path = Path(__file__).parent.parent.parent / "res"
        instance_config_path = Path(os.getenv("TALOS_INSTANCE_CONFIG", base_path / "device_instance_config.yml"))
        modbus_device_path = Path(os.getenv("TALOS_MODBUS_CONFIG", base_path / "modbus_device.yml"))

        logger.info(f"Loading instance config from: {instance_config_path}")
        logger.info(f"Loading modbus config from: {modbus_device_path}")

        # 3. Initialize AsyncDeviceManager
        constraint_config = ConfigManager.load_yaml_file(str(instance_config_path))
        constraint_schema = ConstraintConfigSchema(**constraint_config)

        async_device_manager = AsyncDeviceManager(str(modbus_device_path), constraint_schema)
        await async_device_manager.init()

        app.state.async_device_manager = async_device_manager
        app.state.constraint_schema = constraint_schema
        logger.info("AsyncDeviceManager initialized successfully")
        logger.info("ConstraintConfigSchema stored successfully")

    except Exception as exc:
        logger.error(f"Failed to start API service: {exc}", exc_info=True)
        raise


async def shutdown_event(app: FastAPI) -> None:
    """Clean up shared services before the API application stops."""

    logger.info("Shutting down Talos API Service...")

    device_manager: AsyncDeviceManager | None = getattr(app.state, "async_device_manager", None)
    if not device_manager:
        logger.info("No AsyncDeviceManager instance found during shutdown")
        return

    try:
        await device_manager.shutdown()
        logger.info("AsyncDeviceManager shutdown completed")
    except Exception as exc:
        logger.error(f"Error during AsyncDeviceManager shutdown: {exc}")
