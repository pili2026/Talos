from evaluator.control_evaluator import ControlEvaluator
from executor.control_executor import ControlExecutor
from schema.control_config_schema import ControlConfig
from util.config_manager import ConfigManager
from util.pubsub.subscriber.control_subscriber import ControlSubscriber


def build_control_evaluator(path: str) -> ControlEvaluator:
    """
    Build ControlEvaluator from YAML configuration file.

    Args:
        path: Path to the configuration YAML file

    Returns:
        ControlEvaluator instance with loaded configuration
    """
    config_dict = ConfigManager.load_yaml_file(path)

    # Extract version field (default to "1.0.0" if not present)
    version = config_dict.pop("version", "1.0.0")

    # The remaining config_dict contains the model configurations
    control_config = ControlConfig(version=version, root=config_dict)

    return ControlEvaluator(control_config)


def build_control_subscriber(control_path, pubsub, async_device_manager):
    """
    Build complete control system with evaluator, executor, and subscriber.

    Args:
        control_path: Path to control configuration file
        pubsub: PubSub instance for message handling
        async_device_manager: Device manager for executing actions

    Returns:
        ControlSubscriber instance ready to run
    """
    control_evaluator: ControlEvaluator = build_control_evaluator(control_path)
    control_executor = ControlExecutor(async_device_manager)
    control_subscriber = ControlSubscriber(pubsub=pubsub, evaluator=control_evaluator, executor=control_executor)
    return control_subscriber
