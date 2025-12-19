"""
Talos Unified Service Entry Point

Combines Core monitoring and API services into a single process.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import LiteralString

import uvicorn
from dotenv import load_dotenv

from core.schema.constraint_schema import ConstraintConfigSchema
from core.schema.system_config_schema import SystemConfig
from core.task.snapshot_cleanup_task import SnapshotCleanupTask
from core.util.config_manager import ConfigManager
from core.util.device_health_manager import DeviceHealthManager
from core.util.device_id_policy import get_policy, load_device_id_policy
from core.util.factory.alert_factory import build_alert_subscriber
from core.util.factory.constraint_factory import build_constraint_subscriber
from core.util.factory.control_factory import build_control_subscriber
from core.util.factory.notifier_factory import build_notifiers_and_routing
from core.util.factory.sender_factory import build_sender_subscriber, init_sender
from core.util.factory.snapshot_factory import build_snapshot_subscriber
from core.util.factory.time_factory import build_time_control_subscriber
from core.util.factory.virtual_device_factory import initialize_virtual_device_manager
from core.util.health_check_util import apply_startup_frequencies_with_health_check, initialize_health_check_configs
from core.util.logger_config import LOG_LEVEL_MAP, setup_logging
from core.util.logging_noise import install_asyncio_noise_suppressor, quiet_pymodbus_logs
from core.util.pubsub.in_memory_pubsub import InMemoryPubSub
from core.util.pubsub.pubsub_util import PUBSUB_POLICIES, pubsub_drop_metrics_loop
from core.util.pubsub.subscriber.constraint_evaluator_subscriber import ConstraintSubscriber
from core.util.pubsub.subscriber.control_subscriber import ControlSubscriber
from core.util.sub_registry import SubscriberRegistry
from core.util.virtual_device_manager import VirtualDeviceManager
from device_manager import AsyncDeviceManager
from device_monitor import AsyncDeviceMonitor
from repository.schema.snapshot_storage_schema import SnapshotStorageConfig
from repository.util.db_manager import SQLiteSnapshotDBManager

sys.path.insert(0, str(Path(__file__).parent))

from api.app import create_application

logger = logging.getLogger(__name__)


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Talos Unified Service (Core + API)")

    parser.add_argument("--modbus_device", required=True, help="Modbus device configuration file")
    parser.add_argument("--instance_config", required=True, help="Device instance configuration file")
    parser.add_argument("--alert_config", required=True, help="Alert condition configuration file")
    parser.add_argument("--control_config", required=True, help="Control condition configuration file")
    parser.add_argument("--snapshot_storage_config", required=True, help="Snapshot storage configuration file")
    parser.add_argument("--system_config", default="res/system_config.yml", help="System configuration file")
    parser.add_argument("--time_config", default="res/time_condition.yml", help="Time control configuration file")
    parser.add_argument("--sender_config", default="res/sender_config.yml", help="Data sender configuration file")
    parser.add_argument("--notifier_config", default="res/notifier_config.yml", help="Notifier configuration file")
    parser.add_argument(
        "--virtual_device_config", default=None, help="Path to virtual device configuration file (optional)"
    )
    parser.add_argument("--api-host", default="0.0.0.0", help="API server host")
    parser.add_argument("--api-port", type=int, default=8000, help="API server port")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    return parser.parse_args()


async def main():
    """Main entry point for unified service."""
    args = parse_arguments()

    # Configure logging
    setup_logging(log_to_file=True)
    quiet_pymodbus_logs()
    load_dotenv()
    install_asyncio_noise_suppressor()

    logging.basicConfig(
        level=LOG_LEVEL_MAP.get(args.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("=" * 80)
    logger.info("TALOS UNIFIED SERVICE")
    logger.info("Core Monitoring + API Server")
    logger.info("=" * 80)
    logger.info("")
    logger.info("Configuration Files:")
    logger.info(f"  System Config:    {args.system_config}")
    logger.info(f"  Modbus Device:    {args.modbus_device}")
    logger.info(f"  Instance Config:  {args.instance_config}")
    logger.info(f"  Alert Config:     {args.alert_config}")
    logger.info(f"  Control Config:   {args.control_config}")
    logger.info(f"  Time Config:      {args.time_config}")
    logger.info(f"  Snapshot Storage: {args.snapshot_storage_config}")
    logger.info(f"  Sender Config:    {args.sender_config}")
    logger.info(f"  Notifier Config:  {args.notifier_config}")
    logger.info(f"  Virtual Device Config:  {args.virtual_device_config}")
    logger.info("")
    logger.info("API Configuration:")
    logger.info(f"  Host: {args.api_host}")
    logger.info(f"  Port: {args.api_port}")
    logger.info("=" * 80)

    cleanup_task_handle: asyncio.Task | None = None
    snapshot_db_manager: SQLiteSnapshotDBManager | None = None

    try:
        # ========== Load System Configuration ==========
        logger.info("")
        logger.info("Loading System Configuration")
        logger.info("-" * 80)

        system_config_raw = ConfigManager.load_yaml_file(args.system_config)
        system_config = SystemConfig(**system_config_raw)

        poll_interval: float = system_config.MONITOR_INTERVAL_SECONDS
        logger.info(f"Monitor interval: {poll_interval}s")

        load_device_id_policy(system_config)
        device_id_policy = get_policy()

        enabled_sub_list: list = [name for name, enabled in system_config.SUBSCRIBERS.items() if enabled]
        subscribers: LiteralString = ", ".join(enabled_sub_list) if enabled_sub_list else "(none)"
        logger.info(f"Enabled subscribers: {subscribers}")

        # ========== Initialize Core Components ==========
        logger.info("")
        logger.info("Initializing Core Components")
        logger.info("-" * 80)

        pubsub = InMemoryPubSub()
        logger.info("PubSub initialized (InMemoryPubSub)")

        # Apply topic policies
        for topic, topic_policy in PUBSUB_POLICIES.items():
            try:
                pubsub.set_topic_policy_model(topic, topic_policy)
            except Exception as exc:
                logger.warning(f"[PubSub] Failed to set topic policy: topic={topic}, policy={topic_policy }, err={exc}")

        logger.info("[PubSub] Topic policies applied")

        # Start monitoring task
        asyncio.create_task(pubsub_drop_metrics_loop(pubsub, list(PUBSUB_POLICIES.keys())))

        constraint_config_raw = ConfigManager.load_yaml_file(args.instance_config)
        constraint_schema = ConstraintConfigSchema(**constraint_config_raw)

        async_device_manager = AsyncDeviceManager(
            config_path=args.modbus_device, constraint_config_schema=constraint_schema
        )

        await async_device_manager.init()
        logger.info(f"AsyncDeviceManager initialized ({len(async_device_manager.device_list)} devices)")

        health_params: dict = DeviceHealthManager().calculate_health_params(poll_interval)
        logger.info(f"Health Manager params: {health_params}")

        health_manager = DeviceHealthManager(**health_params)
        logger.info("DeviceHealthManager initialized")

        virtual_device_manager: VirtualDeviceManager | None = initialize_virtual_device_manager(
            config_path=args.virtual_device_config, device_manager=async_device_manager
        )

        monitor = AsyncDeviceMonitor(
            async_device_manager=async_device_manager,
            pubsub=pubsub,
            interval=system_config.MONITOR_INTERVAL_SECONDS,
            health_manager=health_manager,
            virtual_device_manager=virtual_device_manager,
            device_timeout_sec=system_config.MONITOR_DEVICE_TIMEOUT_SEC,
            read_concurrency=system_config.MONITOR_READ_CONCURRENCY,
            log_each_device=system_config.MONITOR_LOG_EACH_DEVICE,
        )

        logger.info("Monitor initialized")

        initialize_health_check_configs(async_device_manager, health_manager)
        logger.info("Health check configs initialized")

        await apply_startup_frequencies_with_health_check(
            device_manager=async_device_manager, health_manager=health_manager, constraint_schema=constraint_schema
        )

        valid_device_ids = {f"{d.model}_{d.slave_id}" for d in async_device_manager.device_list}

        # ========== Build Subscribers ==========
        logger.info("")
        logger.info("Building Subscribers")
        logger.info("-" * 80)

        subscriber_registry = SubscriberRegistry(system_config.SUBSCRIBERS)

        # Time Control Subscriber (returns evaluator for alert integration)
        time_control_subscriber, time_control_evaluator = build_time_control_subscriber(
            pubsub=pubsub,
            valid_device_ids=valid_device_ids,
            time_config_path=args.time_config,
            driver_config=async_device_manager.driver_config_by_model,
            instance_config=constraint_config_raw,
        )
        logger.info("Time control subscriber built")

        # Constraint Subscriber
        constraint_subscriber: ConstraintSubscriber = build_constraint_subscriber(pubsub)
        logger.info("Constraint subscriber built")

        # Alert Subscribers (with time control integration)
        notifier_list, notifier_config = build_notifiers_and_routing(args.notifier_config)
        alert_evaluator_subscriber, alert_notifiers_subscriber = build_alert_subscriber(
            alert_path=args.alert_config,
            pubsub=pubsub,
            valid_device_ids=valid_device_ids,
            notifier_list=notifier_list,
            notifier_config_schema=notifier_config,
            time_control_evaluator=time_control_evaluator,
        )
        logger.info("Alert subscribers built")

        # Control Subscriber
        control_subscriber: ControlSubscriber = build_control_subscriber(
            control_path=args.control_config,
            pubsub=pubsub,
            async_device_manager=async_device_manager,
            health_manager=health_manager,
        )
        logger.info("Control subscriber built")

        # Data Sender
        legacy_sender, sender_subscriber = build_sender_subscriber(
            pubsub=pubsub,
            async_device_manager=async_device_manager,
            sender_config_path=args.sender_config,
            series_number=device_id_policy._config.SERIES,
        )
        logger.info("Data sender built")

        # Snapshot Storage
        snapshot_storage_raw: dict = ConfigManager.load_yaml_file(args.snapshot_storage_config)
        snapshot_storage = SnapshotStorageConfig(**snapshot_storage_raw)
        snapshot_saver_subscriber, snapshot_repo, snapshot_db_manager = await build_snapshot_subscriber(
            snapshot_config_path=args.snapshot_storage_config,
            pubsub=pubsub,
        )

        if snapshot_saver_subscriber:
            logger.info("[SnapshotStorage] Enabled")

            if snapshot_repo:
                cleanup_task = SnapshotCleanupTask(
                    repository=snapshot_repo,
                    db_path=snapshot_storage.db_path,
                    retention_days=snapshot_storage.retention_days,
                    cleanup_interval_hours=snapshot_storage.cleanup_interval_hours,
                    vacuum_interval_days=snapshot_storage.vacuum_interval_days,
                )
                cleanup_task_handle: asyncio.Task = cleanup_task.start()

                logger.info("[SnapshotStorage] Cleanup task started")
            else:
                logger.warning("[SnapshotStorage] Snapshot enabled but repository is missing; cleanup disabled")
        else:
            logger.info("[SnapshotStorage] Disabled")

        # ========== Initialize API ==========
        logger.info("")
        logger.info("Initializing API Server")
        logger.info("-" * 80)

        app = create_application()

        # Inject shared instances via TalosAppState
        app.state.talos.async_device_manager = async_device_manager
        app.state.talos.constraint_schema = constraint_schema
        app.state.talos.pubsub = pubsub
        app.state.talos.health_manager = health_manager
        app.state.talos.unified_mode = True
        app.state.talos.snapshot_db_path = snapshot_storage.db_path
        app.state.talos.snapshot_config_path = args.snapshot_storage_config

        logger.info("Shared instances injected:")
        logger.info("  - AsyncDeviceManager")
        logger.info("  - ConstraintConfigSchema")
        logger.info("  - InMemoryPubSub")
        logger.info("  - DeviceHealthManager")
        logger.info("  - Snapshot config")
        logger.info(f"   {app.state.talos}")

        config = uvicorn.Config(
            app, host=args.api_host, port=args.api_port, log_level=args.log_level.lower(), access_log=False
        )
        server = uvicorn.Server(config)
        logger.info(f"API server configured (http://{args.api_host}:{args.api_port})")

        # ========== Register Subscribers ==========
        logger.info("")
        logger.info("Registering Subscribers")
        logger.info("-" * 80)

        subscriber_registry.register("MONITOR", monitor.run)
        subscriber_registry.register("TIME_CONTROL", time_control_subscriber.run)
        subscriber_registry.register("CONSTRAINT", constraint_subscriber.run)
        subscriber_registry.register("ALERT", alert_evaluator_subscriber.run)
        subscriber_registry.register("ALERT_NOTIFIERS", alert_notifiers_subscriber.run)
        subscriber_registry.register("CONTROL", control_subscriber.run)
        subscriber_registry.register("DATA_SENDER", sender_subscriber.run)

        if snapshot_saver_subscriber:
            subscriber_registry.register("SNAPSHOT_SAVER", snapshot_saver_subscriber.run)

        await init_sender(legacy_sender)

        logger.info(f"Registered {len(subscriber_registry.subs)} subscribers")

        # ========== Start All Services ==========
        logger.info("")
        logger.info("=" * 80)
        logger.info("STARTING ALL SERVICES")
        logger.info("=" * 80)

        await subscriber_registry.start_enabled_sub()

        logger.info("Started subscribers:")
        for name in subscriber_registry.subs.keys():
            if system_config.SUBSCRIBERS.get(name, False):
                logger.info(f"{name}")
            else:
                logger.info(f"{name} (disabled)")

        logger.info("")
        logger.info("=" * 80)
        logger.info("TALOS UNIFIED SERVICE RUNNING")
        logger.info("=" * 80)
        logger.info(f"API: http://localhost:{args.api_port}/docs")
        logger.info("Press Ctrl+C to stop")
        logger.info("=" * 80)

        await server.serve()

    except KeyboardInterrupt:
        logger.info("")
        logger.info("=" * 80)
        logger.info("SHUTDOWN SIGNAL RECEIVED")
        logger.info("=" * 80)

    except Exception as e:
        logger.error("")
        logger.error("=" * 80)
        logger.error("FATAL ERROR")
        logger.error("=" * 80)
        logger.error(f"Error: {e}", exc_info=True)
        raise

    finally:
        logger.info("")
        logger.info("=" * 80)
        logger.info("SHUTTING DOWN")
        logger.info("=" * 80)

        try:
            if "subscriber_registry" in locals():
                await subscriber_registry.stop_all()
                logger.info("All subscribers stopped")

            # Stop cleanup task
            if cleanup_task_handle:
                cleanup_task_handle.cancel()
                try:
                    await cleanup_task_handle
                except asyncio.CancelledError:
                    logger.info("[SnapshotStorage] Cleanup task stopped")

            # Close SQLite engine
            if snapshot_db_manager:
                logger.info("[SnapshotStorage] Closing SQLite engine")
                await snapshot_db_manager.close_engine()
                logger.info("[SnapshotStorage] SQLite engine closed")

            if "pubsub" in locals():
                await pubsub.close()
                logger.info("PubSub closed")

            if "async_device_manager" in locals():
                await async_device_manager.shutdown()
                logger.info("AsyncDeviceManager shutdown")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

        logger.info("=" * 80)
        logger.info("SHUTDOWN COMPLETE")
        logger.info("=" * 80)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"Failed to start: {e}", exc_info=True)
        sys.exit(1)
