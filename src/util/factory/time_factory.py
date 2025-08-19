from evaluator.time_evalutor import TimeControlEvaluator
from executor.time_control_executor import TimeControlExecutor
from time_control_handler import TimeControlHandler
from util.config_manager import ConfigManager
from util.pubsub.base import PubSub
from util.pubsub.subscriber.time_control_subscriber import TimeControlSubscriber


def build_time_control_subscriber(
    pubsub: PubSub, valid_device_ids: set[str], time_config_path: str
) -> TimeControlSubscriber:
    time_config: dict = ConfigManager.load_yaml_file(time_config_path)
    time_control_evaluator = TimeControlEvaluator(time_config["work_hours"])
    time_control_executor = TimeControlExecutor(pubsub)
    time_control_handler = TimeControlHandler(
        pubsub=pubsub,
        time_control_evaluator=time_control_evaluator,
        executor=time_control_executor,
        expected_devices=valid_device_ids,
    )
    time_control_subscriber = TimeControlSubscriber(
        pubsub=pubsub,
        time_control_handler=time_control_handler,
    )

    return time_control_subscriber
