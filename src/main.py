import argparse
import asyncio

from dotenv import load_dotenv

from device_manager import AsyncDeviceManager
from device_monitor import AsyncDeviceMonitor
from evaluator.alert_evaluator import AlertEvaluator
from evaluator.constraint_evaluator import ConstraintEvaluator
from evaluator.control_evaluator import ControlEvaluator
from evaluator.time_evalutor import TimeControlEvaluator
from executor.control_executor import ControlExecutor
from util.config_manager import ConfigManager
from util.evaluator_factory import build_alert_evaluator, build_control_evaluator
from util.logger_config import setup_logging
from util.notifier.email_notifier import EmailNotifier
from util.pubsub.in_memory_pubsub import InMemoryPubSub
from util.pubsub.subscriber.alert_evaluator_subscriber import AlertEvaluatorSubscriber
from util.pubsub.subscriber.alert_notifier_subscriber import AlertNotifierSubscriber
from util.pubsub.subscriber.constraint_evaluator_subscriber import ConstraintSubscriber
from util.pubsub.subscriber.control_subscriber import ControlSubscriber
from util.pubsub.subscriber.time_control_subscriber import TimeControlSubscriber


async def main(alert_path: str, control_path: str, modbus_device_path: str, instance_config_path: str):
    setup_logging(log_to_file=True)
    load_dotenv()

    pubsub = InMemoryPubSub()
    instance_config: dict = ConfigManager.load_yaml_file(instance_config_path)
    async_device_manager = AsyncDeviceManager(modbus_device_path, instance_config)
    await async_device_manager.init()

    monitor = AsyncDeviceMonitor(async_device_manager, pubsub)

    valid_device_ids = {f"{device.model}_{device.slave_id}" for device in async_device_manager.device_list}

    constraint_evaluator = ConstraintEvaluator(pubsub)
    constraint_subscriber = ConstraintSubscriber(pubsub, constraint_evaluator)

    alert_evaluator: AlertEvaluator = build_alert_evaluator(alert_path, valid_device_ids)
    email_notifier = EmailNotifier()

    alert_eval_subscriber = AlertEvaluatorSubscriber(pubsub, alert_evaluator)
    alert_notifier_subscriber = AlertNotifierSubscriber(pubsub, [email_notifier])

    control_evaluator: ControlEvaluator = build_control_evaluator(control_path)
    control_executor = ControlExecutor(async_device_manager)
    control_subscriber = ControlSubscriber(pubsub=pubsub, evaluator=control_evaluator, executor=control_executor)

    time_config = ConfigManager.load_yaml_file("res/time_control.yml")
    time_control_evaluator = TimeControlEvaluator(time_config["work_hours"])
    time_control_subscriber = TimeControlSubscriber(
        pubsub=pubsub,
        time_control_evaluator=time_control_evaluator,
        expected_devices=valid_device_ids,
    )

    await asyncio.gather(
        monitor.run(),  # SNAPSHOT from all devices
        time_control_subscriber.run(),  # Block/allow devices based on time
        constraint_subscriber.run(),  # Only process SNAPSHOT_ALLOWED
        alert_eval_subscriber.run(),  # Only process SNAPSHOT_ALLOWED
        control_subscriber.run(),  # Only process SNAPSHOT_ALLOWED
        alert_notifier_subscriber.run(),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--alert", default="res/alert_condition.yml", help="Path to alert condition YAML")
    parser.add_argument("--control", default="res/control_condition.yml", help="Path to control condition YAML")
    parser.add_argument("--modbus_device", default="res/modbus_device.yml", help="Path to modbus device YAML")
    parser.add_argument(
        "--instance_config", default="res/device_instance_config.yml", help="Path to instance config YAML"
    )

    args = parser.parse_args()
    asyncio.run(
        main(
            alert_path=args.alert,
            control_path=args.control,
            modbus_device_path=args.modbus_device,
            instance_config_path=args.instance_config,
        )
    )
