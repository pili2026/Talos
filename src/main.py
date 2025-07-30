import asyncio

from dotenv import load_dotenv

from alert_evaluator import AlertEvaluator
from control_evaluator import ControlEvaluator
from control_executor import ControlExecutor
from device_manager import AsyncDeviceManager
from device_monitor import AsyncDeviceMonitor
from util.evaluator_factory import build_alert_evaluator, build_control_evaluator
from util.logger_config import setup_logging
from util.notifier.email_notifier import EmailNotifier
from util.pubsub.in_memory_pubsub import InMemoryPubSub
from util.pubsub.subscriber.alert_evaluator_subscriber import AlertEvaluatorSubscriber
from util.pubsub.subscriber.alert_notifier_subscriber import AlertNotifierSubscriber
from util.pubsub.subscriber.control_subscriber import ControlSubscriber


async def main():
    setup_logging(log_to_file=True)
    load_dotenv()

    pubsub = InMemoryPubSub()
    async_device_manager = AsyncDeviceManager()
    await async_device_manager.init()

    monitor = AsyncDeviceMonitor(async_device_manager, pubsub)

    valid_device_ids = {f"{device.model}_{device.slave_id}" for device in async_device_manager.device_list}

    alert_evaluator: AlertEvaluator = build_alert_evaluator("res/alert_condition.yml", valid_device_ids)
    email_notifier = EmailNotifier()

    alert_eval_subscriber = AlertEvaluatorSubscriber(pubsub, alert_evaluator)
    alert_notifier_subscriber = AlertNotifierSubscriber(pubsub, [email_notifier])

    control_evaluator: ControlEvaluator = build_control_evaluator("res/control_condition.yml")
    control_executor = ControlExecutor(async_device_manager)
    control_subscriber = ControlSubscriber(pubsub, control_evaluator, control_executor)

    await asyncio.gather(
        monitor.run(),
        control_subscriber.run(),
        alert_eval_subscriber.run(),
        alert_notifier_subscriber.run(),
    )


if __name__ == "__main__":
    asyncio.run(main())
