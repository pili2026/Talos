from control_config import ControlConfig
from evaluator.control_evaluator import ControlEvaluator
from executor.control_executor import ControlExecutor
from util.config_manager import ConfigManager
from util.pubsub.subscriber.control_subscriber import ControlSubscriber


def build_control_evaluator(path: str) -> ControlEvaluator:
    config_dict = ConfigManager.load_yaml_file(path)
    control_config = ControlConfig.model_validate({"root": config_dict})
    return ControlEvaluator(control_config)


def build_control_subscriber(control_path, pubsub, async_device_manager):
    control_evaluator: ControlEvaluator = build_control_evaluator(control_path)
    control_executor = ControlExecutor(async_device_manager)
    control_subscriber = ControlSubscriber(pubsub=pubsub, evaluator=control_evaluator, executor=control_executor)
    return control_subscriber
