from core.evaluator.control_evaluator import ControlEvaluator
from core.executor.control_executor import ControlExecutor
from core.schema.constraint_schema import ConstraintConfigSchema
from core.schema.control_config_schema import ControlConfig
from core.util.config_manager import ConfigManager
from core.util.device_health_manager import DeviceHealthManager
from core.util.pubsub.base import PubSub
from core.util.pubsub.subscriber.control_subscriber import ControlSubscriber
from device_manager import AsyncDeviceManager


def build_control_evaluator(path: str, constraint_config_schema: ConstraintConfigSchema = None) -> ControlEvaluator:
    """
    Build ControlEvaluator from YAML configuration file.
    Args:
        path: Path to the configuration YAML file
        constraint_config: Constraint configuration for emergency override logic
    Returns:
        ControlEvaluator instance with loaded configuration
    """
    config_dict = ConfigManager.load_yaml_file(path)
    # Extract version field (default to "1.0.0" if not present)
    version = config_dict.pop("version", "1.0.0")
    # The remaining config_dict contains the model configurations
    control_config = ControlConfig(version=version, root=config_dict)
    return ControlEvaluator(control_config, constraint_config_schema)  # Pass in constraint_config


def build_control_subscriber(
    control_path: str,
    pubsub: PubSub,
    async_device_manager: AsyncDeviceManager,
    health_manager: DeviceHealthManager | None = None,
) -> ControlSubscriber:
    """
    Build complete control system with evaluator, executor, and subscriber.
    Args:
        control_path: Path to control configuration file
        pubsub: PubSub instance for message handling
        async_device_manager: Device manager for executing actions
    Returns:
        ControlSubscriber instance ready to run
    """
    # From async_device_manager get constraint_config
    constraint_config_schema: ConstraintConfigSchema = async_device_manager.constraint_config_schema

    control_evaluator: ControlEvaluator = build_control_evaluator(control_path, constraint_config_schema)
    control_executor = ControlExecutor(async_device_manager, health_manager)
    control_subscriber = ControlSubscriber(pubsub=pubsub, evaluator=control_evaluator, executor=control_executor)
    return control_subscriber
