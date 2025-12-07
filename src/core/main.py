import argparse
import asyncio
import logging

from dotenv import load_dotenv

from core.schema.constraint_schema import ConstraintConfigSchema
from core.schema.system_config_schema import DeviceIdPolicyConfig, SystemConfig
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
from core.util.logger_config import setup_logging
from core.util.logging_noise import install_asyncio_noise_suppressor, quiet_pymodbus_logs
from core.util.pubsub.in_memory_pubsub import InMemoryPubSub
from core.util.pubsub.subscriber.constraint_evaluator_subscriber import ConstraintSubscriber
from core.util.pubsub.subscriber.control_subscriber import ControlSubscriber
from core.util.sub_registry import SubscriberRegistry
from device_manager import AsyncDeviceManager
from device_monitor import AsyncDeviceMonitor
from repository.schema.snapshot_storage_schema import SnapshotStorageConfig

logger = logging.getLogger("CoreMain")


async def main(
    alert_path: str,
    control_path: str,
    modbus_device_path: str,
    instance_config_path: str,
    sender_config_path: str,
    time_config_path: str,
    system_config_path: str,
    notifier_config_path: str,
    snapshot_storage_path: str,
):
    setup_logging(log_to_file=True)
    quiet_pymodbus_logs()
    load_dotenv()
    install_asyncio_noise_suppressor()

    # ----------------------------------------------------------------------
    # Load system config
    # ----------------------------------------------------------------------
    system_config_raw: dict = ConfigManager.load_yaml_file(system_config_path)
    system_config = SystemConfig(**system_config_raw)

    load_device_id_policy(system_config)
    policy = get_policy()

    # ----------------------------------------------------------------------
    # Load snapshot storage config
    # ----------------------------------------------------------------------
    snapshot_storage_raw: dict = ConfigManager.load_yaml_file(snapshot_storage_path)
    snapshot_storage = SnapshotStorageConfig(**snapshot_storage_raw)

    # ----------------------------------------------------------------------
    # Initialize pubsub & device manager
    # ----------------------------------------------------------------------
    pubsub = InMemoryPubSub()

    health_manager = DeviceHealthManager()
    logger.info("DeviceHealthManager initialized")

    constraint_config_raw: dict = ConfigManager.load_yaml_file(instance_config_path)
    constraint_config = ConstraintConfigSchema(**constraint_config_raw)

    async_device_manager = AsyncDeviceManager(modbus_device_path, constraint_config)
    await async_device_manager.init()

    monitor = AsyncDeviceMonitor(
        async_device_manager=async_device_manager,
        pubsub=pubsub,
        interval=system_config.MONITOR_INTERVAL_SECONDS,
        health_manager=health_manager,
    )

    valid_device_ids: set[str] = {f"{device.model}_{device.slave_id}" for device in async_device_manager.device_list}

    subscriber_registry = SubscriberRegistry(system_config.SUBSCRIBERS)

    # ----------------------------------------------------------------------
    # Build subscribers (constraint / alert / control / time)
    # ----------------------------------------------------------------------
    time_control_subscriber, time_control_evaluator = build_time_control_subscriber(
        pubsub=pubsub,
        valid_device_ids=valid_device_ids,
        time_config_path=time_config_path,
        driver_config=async_device_manager.driver_config_by_model,
        instance_config=constraint_config_raw,
    )

    constraint_subscriber: ConstraintSubscriber = build_constraint_subscriber(pubsub)

    notifier_list, notifier_config = build_notifiers_and_routing(notifier_config_path)

    alert_evaluator_subscriber, alert_notifiers_subscriber = build_alert_subscriber(
        alert_path=alert_path,
        pubsub=pubsub,
        valid_device_ids=valid_device_ids,
        notifier_list=notifier_list,
        notifier_config_schema=notifier_config,
        time_control_evaluator=time_control_evaluator,
    )

    control_subscriber: ControlSubscriber = build_control_subscriber(
        control_path=control_path, pubsub=pubsub, async_device_manager=async_device_manager
    )

    # ----------------------------------------------------------------------
    # Data sender
    # ----------------------------------------------------------------------
    legacy_sender, sender_subscriber = build_sender_subscriber(
        pubsub=pubsub,
        async_device_manager=async_device_manager,
        sender_config_path=sender_config_path,
        series_number=policy._config.SERIES,
    )

    # ----------------------------------------------------------------------
    # Snapshot storage (SQLite DB)
    # ----------------------------------------------------------------------
    snapshot_saver_subscriber, snapshot_repo, snapshot_db_manager = await build_snapshot_subscriber(
        snapshot_config_path=snapshot_storage_path,
        pubsub=pubsub,
    )

    cleanup_task_handle = None

    if snapshot_saver_subscriber:
        # Use the repository returned by factory (no duplicate creation)
        cleanup_task = SnapshotCleanupTask(
            repository=snapshot_repo,
            db_path=snapshot_storage.db_path,
            retention_days=snapshot_storage.retention_days,
            cleanup_interval_hours=snapshot_storage.cleanup_interval_hours,
            vacuum_interval_days=snapshot_storage.vacuum_interval_days,
        )
        cleanup_task_handle: asyncio.Task = cleanup_task.start()

        logger.info("[SnapshotStorage] SQLite snapshot storage initialized")
    else:
        logger.info("[SnapshotStorage] Disabled")

    # ----------------------------------------------------------------------
    # Register subscribers
    # ----------------------------------------------------------------------
    subscriber_registry.register("MONITOR", monitor.run)
    subscriber_registry.register("TIME_CONTROL", time_control_subscriber.run)
    subscriber_registry.register("CONSTRAINT", constraint_subscriber.run)
    subscriber_registry.register("ALERT", alert_evaluator_subscriber.run)
    subscriber_registry.register("ALERT_NOTIFIERS", alert_notifiers_subscriber.run)
    subscriber_registry.register("CONTROL", control_subscriber.run)
    subscriber_registry.register("DATA_SENDER", sender_subscriber.run)

    if snapshot_saver_subscriber:
        subscriber_registry.register("SNAPSHOT_SAVER", snapshot_saver_subscriber.run)

    # Sender startup
    await init_sender(legacy_sender)

    # ----------------------------------------------------------------------
    # Start all subscribers
    # ----------------------------------------------------------------------
    try:
        logger.info("Starting subscribers...")
        await subscriber_registry.start_enabled_sub()

        # Keep running
        await asyncio.Event().wait()

    finally:
        logger.info("Shutting down...")

        await subscriber_registry.stop_all()

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--alert_config", default="res/alert_condition.yml", help="Path to alert condition YAML")
    parser.add_argument("--control_config", default="res/control_condition.yml", help="Path to control condition YAML")
    parser.add_argument("--modbus_device", default="res/modbus_device.yml", help="Path to modbus device YAML")
    parser.add_argument(
        "--instance_config", default="res/device_instance_config.yml", help="Path to instance config YAML"
    )
    parser.add_argument("--sender_config", default="res/sender_config.yml", help="Path to sender config YAML")
    parser.add_argument("--time_config", default="res/time_condition.yml", help="Path to time condition config YAML")
    parser.add_argument("--system_config", default="res/system_config.yml", help="Path to system config YAML")
    parser.add_argument("--notifier_config", default="res/notifier_config.yml", help="Path to notifier config YAML")
    parser.add_argument(
        "--snapshot_storage_config", default="res/snapshot_storage.yml", help="Path to snapshot storage config YAML"
    )

    args = parser.parse_args()
    asyncio.run(
        main(
            alert_path=args.alert_config,
            control_path=args.control_config,
            modbus_device_path=args.modbus_device,
            instance_config_path=args.instance_config,
            sender_config_path=args.sender_config,
            time_config_path=args.time_config,
            system_config_path=args.system_config,
            notifier_config_path=args.notifier_config,
            snapshot_storage_path=args.snapshot_storage_config,
        )
    )
