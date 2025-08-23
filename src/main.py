import argparse
import asyncio
import logging

from dotenv import load_dotenv

from device_manager import AsyncDeviceManager
from device_monitor import AsyncDeviceMonitor
from util.config_manager import ConfigManager
from util.factory.alert_factory import build_alert_subscriber
from util.factory.constraint_factory import build_constraint_subscriber
from util.factory.control_factory import build_control_subscriber
from util.factory.sender_factory import build_sender_subscriber, init_sender
from util.factory.time_factory import build_time_control_subscriber
from util.logger_config import setup_logging
from util.notifier.email_notifier import EmailNotifier
from util.pubsub.in_memory_pubsub import InMemoryPubSub
from util.pubsub.subscriber.constraint_evaluator_subscriber import ConstraintSubscriber
from util.pubsub.subscriber.control_subscriber import ControlSubscriber
from util.pubsub.subscriber.time_control_subscriber import TimeControlSubscriber
from util.sub_registry import SubscriberRegistry

logger = logging.getLogger("Main")


async def main(
    alert_path: str,
    control_path: str,
    modbus_device_path: str,
    instance_config_path: str,
    sender_config_path: str,
    mail_config_path: str,
    time_config_path: str,
):
    setup_logging(log_to_file=True)
    load_dotenv()

    system_config: dict = ConfigManager.load_yaml_file("res/system_config.yml")

    pubsub = InMemoryPubSub()
    instance_config: dict = ConfigManager.load_yaml_file(instance_config_path)
    async_device_manager = AsyncDeviceManager(modbus_device_path, instance_config)
    await async_device_manager.init()

    monitor = AsyncDeviceMonitor(
        async_device_manager=async_device_manager,
        pubsub=pubsub,
        interval=system_config.get("MONITOR_INTERVAL_SECONDS", 1.0),
    )

    valid_device_ids: set[str] = {f"{device.model}_{device.slave_id}" for device in async_device_manager.device_list}
    email_notifier = EmailNotifier(mail_config_path)

    enabled_sub: dict[str, bool] = system_config.get("SUBSCRIBERS", {})
    subscriber_registry = SubscriberRegistry(enabled_sub)

    constraint_subscriber: ConstraintSubscriber = build_constraint_subscriber(pubsub)
    alert_evaluator_subscriber, alert_notifiers_subscriber = build_alert_subscriber(
        alert_path=alert_path, pubsub=pubsub, valid_device_ids=valid_device_ids, notifier_list=[email_notifier]
    )
    control_subscriber: ControlSubscriber = build_control_subscriber(
        control_path=control_path, pubsub=pubsub, async_device_manager=async_device_manager
    )
    time_control_subscriber: TimeControlSubscriber = build_time_control_subscriber(
        pubsub=pubsub, valid_device_ids=valid_device_ids, time_config_path=time_config_path
    )

    legacy_sender, sender_subscriber = build_sender_subscriber(
        pubsub=pubsub, async_device_manager=async_device_manager, sender_config_path=sender_config_path
    )

    subscriber_registry.register("MONITOR", monitor.run)
    subscriber_registry.register("TIME_CONTROL", time_control_subscriber.run)
    subscriber_registry.register("CONSTRAINT", constraint_subscriber.run)
    subscriber_registry.register("ALERT", alert_evaluator_subscriber.run)
    subscriber_registry.register("ALERT_NOTIFIERS", alert_notifiers_subscriber.run)
    subscriber_registry.register("CONTROL", control_subscriber.run)
    subscriber_registry.register("DATA_SENDER", sender_subscriber.run)

    await init_sender(legacy_sender)

    try:
        logger.info("Starting subscribers...")
        await subscriber_registry.start_enabled_sub()

        # Main loop to keep the program running, replace with actual event loop logic(like FastAPI or similar)
        await asyncio.Event().wait()
    finally:
        logger.info("stopped")
        await subscriber_registry.stop_all()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--alert_config", default="res/alert_condition.yml", help="Path to alert condition YAML")
    parser.add_argument("--control_config", default="res/control_condition.yml", help="Path to control condition YAML")
    parser.add_argument("--modbus_device", default="res/modbus_device.yml", help="Path to modbus device YAML")
    parser.add_argument(
        "--instance_config", default="res/device_instance_config.yml", help="Path to instance config YAML"
    )
    parser.add_argument("--sender_config", default="res/sender_config.yml", help="Path to sender config YAML")
    parser.add_argument("--mail_config", default="res/mail_config.yml", help="Path to mail config YAML")
    parser.add_argument("--time_config", default="res/time_condition.yml", help="Path to time condition config YAML")

    args = parser.parse_args()
    asyncio.run(
        main(
            alert_path=args.alert_config,
            control_path=args.control_config,
            modbus_device_path=args.modbus_device,
            instance_config_path=args.instance_config,
            sender_config_path=args.sender_config,
            mail_config_path=args.mail_config,
            time_config_path=args.time_config,
        )
    )
