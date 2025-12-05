from device.generic.capability import CapabilityResolver
from evaluator.time_evalutor import TimeControlEvaluator
from executor.time_control_executor import TimeControlExecutor
from handler.time_control_handler import TimeControlHandler
from schema.time_control_schema import TimeControlConfig
from util.config_manager import ConfigManager
from util.pubsub.base import PubSub
from util.pubsub.subscriber.time_control_subscriber import TimeControlSubscriber


def build_time_control_subscriber(
    pubsub: PubSub,
    valid_device_ids: set[str],
    time_config_path: str,
    *,
    driver_config: dict[str, str] | None = None,  # e.g., {"IMA_C": "res/driver/ima_c.yml"}
    instance_config: str | None = None,  # e.g., "res/device_instance_config.yml"
) -> tuple[TimeControlSubscriber, TimeControlEvaluator]:
    """
    Build components related to TimeControl.

    Returns:
        Tuple of (subscriber, evaluator) to enable other components to access evaluator

    - Original parameters remain unchanged; new keyword arguments are optional,
      used to inject driver/instance capability settings.
    - If driver paths are not provided, DO translation falls back to heuristics
      (may not be able to pick up on_off_binding).
    """
    raw_time_config: dict = ConfigManager.load_yaml_file(time_config_path)
    time_config: TimeControlConfig = TimeControlConfig.model_validate(raw_time_config)

    capability_resolver = CapabilityResolver(driver_config, instance_config)

    time_control_evaluator = TimeControlEvaluator(time_config)
    time_control_executor = TimeControlExecutor(pubsub, capability_resolver)
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

    return time_control_subscriber, time_control_evaluator
