"""Startup and shutdown hooks for the FastAPI application."""

import logging
import os
from pathlib import Path

from fastapi import FastAPI

from api.repository.config_repository import ConfigRepository
from api.service.provision_service import ProvisionService
from api.service.system_config_service import SystemConfigService
from api.service.wifi_service import WiFiService
from core.schema.constraint_schema import ConstraintConfigSchema
from core.schema.system_config_schema import SystemConfig
from core.util.config_manager import ConfigManager
from core.util.yaml_manager import YAMLManager
from device_manager import AsyncDeviceManager

logger = logging.getLogger(__name__)


def _init_system_config_service_and_provision(
    yaml_manager: YAMLManager, system_config: SystemConfig | None
) -> tuple[SystemConfigService, ProvisionService]:
    system_config_service = SystemConfigService(
        yaml_manager=yaml_manager,
        system_config=system_config,
    )
    provision_service = ProvisionService(
        system_config=system_config,
        on_port_updated=system_config_service.update_reverse_ssh_port,
    )
    return system_config_service, provision_service


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
            logger.debug(f"State: {app.state.talos}")

            # Verify required components
            if app.state.talos.constraint_schema is None:
                raise RuntimeError("constraint_schema not injected")
            if app.state.talos.pubsub is None:
                raise RuntimeError("pubsub not injected")
            if app.state.talos.wifi_service is None:
                raise RuntimeError("wifi_service not injected")
            if app.state.talos.provision_service is None:
                raise RuntimeError("provision_service not injected")

            logger.info("All shared instances verified")

            # Load snapshot config (if not already set by main_service)
            if app.state.talos.snapshot_db_path is None:
                base_res_path = Path(__file__).parent.parent.parent / "res"
                snapshot_config_path = Path(os.getenv("TALOS_SNAPSHOT_CONFIG", base_res_path / "snapshot_storage.yml"))
                snapshot_cfg = ConfigManager.load_yaml_file(str(snapshot_config_path))

                app.state.talos.snapshot_db_path = snapshot_cfg.get("db_path", "./data/snapshots.db")
                app.state.talos.snapshot_config_path = str(snapshot_config_path)

                logger.info(f"Snapshot config loaded (db={app.state.talos.snapshot_db_path})")

            # Initialize YAMLManager and ConfigManager (if not provided by main_service)
            if app.state.talos.yaml_manager is None:
                base_res_path = Path(__file__).parent.parent.parent / "res"
                yaml_manager = YAMLManager(base_res_path, backup_count=10)
                config_manager_with_yaml = ConfigManager(yaml_manager=yaml_manager)

                app.state.talos.yaml_manager = yaml_manager
                app.state.talos.config_manager = config_manager_with_yaml

                logger.info("YAMLManager and ConfigManager initialized (unified mode)")

            # Initialize SystemConfigService with port sync callback
            # Note: in unified mode, provision_service is already injected by main_service,
            # so we wrap it with the callback here instead of recreating it
            system_config_service = SystemConfigService(
                yaml_manager=app.state.talos.yaml_manager, system_config=app.state.talos.system_config
            )
            app.state.talos.provision_service.on_port_updated = system_config_service.update_reverse_ssh_port
            app.state.talos.system_config_service = system_config_service

            logger.info("SystemConfigService initialized (unified mode)")
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
        system_config_path = Path(os.getenv("TALOS_SYSTEM_CONFIG", base_res_path / "system_config.yml"))

        logger.info(f"Instance config: {instance_config_path}")
        logger.info(f"Modbus config: {modbus_device_path}")
        logger.info(f"System config: {system_config_path}")

        # Load SystemConfig
        system_config_raw = ConfigManager.load_yaml_file(str(system_config_path))
        system_config = SystemConfig(**system_config_raw)
        logger.info("SystemConfig loaded")

        # Initialize components
        constraint_config = ConfigManager.load_yaml_file(str(instance_config_path))
        constraint_schema = ConstraintConfigSchema(**constraint_config)

        async_device_manager = AsyncDeviceManager(str(modbus_device_path), constraint_schema)
        await async_device_manager.init()
        logger.info(f"AsyncDeviceManager initialized ({len(async_device_manager.device_list)} devices)")

        # Initialize configuration management
        yaml_manager = YAMLManager(base_res_path, backup_count=10)
        config_manager_with_yaml = ConfigManager(yaml_manager=yaml_manager)
        logger.info("YAMLManager initialized (version control enabled)")

        # Initialize WiFiService
        wifi_service = WiFiService()
        logger.info("WiFiService initialized")

        # Initialize SystemConfigService + ProvisionService with port sync callback
        system_config_service, provision_service = _init_system_config_service_and_provision(
            yaml_manager=yaml_manager,
            system_config=system_config,
        )
        logger.info("SystemConfigService initialized")
        logger.info("ProvisionService initialized (with port sync callback)")

        # Update app state
        app.state.talos.async_device_manager = async_device_manager
        app.state.talos.constraint_schema = constraint_schema
        app.state.talos.system_config = system_config
        app.state.talos.wifi_service = wifi_service
        app.state.talos.provision_service = provision_service
        app.state.talos.system_config_service = system_config_service
        app.state.talos.yaml_manager = yaml_manager
        app.state.talos.config_manager = config_manager_with_yaml
        app.state.talos.unified_mode = False

        # Load snapshot config
        snapshot_config_path = Path(os.getenv("TALOS_SNAPSHOT_CONFIG", base_res_path / "snapshot_storage.yml"))
        snapshot_cfg = ConfigManager.load_yaml_file(str(snapshot_config_path))

        app.state.talos.snapshot_db_path = snapshot_cfg.get("db_path", "./data/snapshots.db")
        app.state.talos.snapshot_config_path = str(snapshot_config_path)

        logger.info("Snapshot config loaded")
        logger.debug(f"State: {app.state.talos}")
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
        logger.info("UNIFIED MODE: Cleanup handled by main_service.py")
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
