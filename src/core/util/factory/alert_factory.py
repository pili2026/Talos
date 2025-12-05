import logging

from core.evaluator.alert_evaluator import AlertEvaluator
from core.evaluator.time_evalutor import TimeControlEvaluator
from core.model.enum.alert_enum import AlertSeverity
from core.schema.alert_config_schema import AlertConfig
from core.schema.notifier_schema import NotificationConfigSchema, RoutingRule
from core.util.config_manager import ConfigManager
from core.util.notifier.base import BaseNotifier
from core.util.pubsub.base import PubSub
from core.util.pubsub.subscriber.alert_evaluator_subscriber import AlertEvaluatorSubscriber
from core.util.pubsub.subscriber.alert_notifier_subscriber import AlertNotifierSubscriber

logger = logging.getLogger("AlertFactory")


def build_alert_subscriber(
    alert_path: str,
    pubsub: PubSub,
    valid_device_ids: set[str],
    notifier_list: list[BaseNotifier],
    notifier_config_schema: NotificationConfigSchema,
    time_control_evaluator: TimeControlEvaluator | None = None,
) -> tuple[AlertEvaluatorSubscriber, AlertNotifierSubscriber]:
    """
    Build alert evaluator and notifier subscribers.

    Args:
        alert_path: Path to alert configuration YAML file
        pubsub: PubSub instance for message passing
        valid_device_ids: Set of valid device IDs (model_slaveid format)
        notifier_list: List of notifier instances
        notifier_config_schema: Notification configuration schema

    Returns:
        Tuple of (alert_evaluator_subscriber, alert_notifier_subscriber)
    """
    alert_evaluator: AlertEvaluator = build_alert_evaluator(
        path=alert_path, valid_device_ids=valid_device_ids, time_control_evaluator=time_control_evaluator
    )
    alert_eval_subscriber = AlertEvaluatorSubscriber(pubsub, alert_evaluator)

    routing_rule_dict: dict[AlertSeverity, RoutingRule] = notifier_config_schema.strategy.routing
    alert_notifier_subscriber = AlertNotifierSubscriber(
        pubsub=pubsub,
        notifier_list=notifier_list,
        routing_rules=routing_rule_dict,
        config_schema=notifier_config_schema,
    )

    return alert_eval_subscriber, alert_notifier_subscriber


def build_alert_evaluator(
    path: str, valid_device_ids: set[str], time_control_evaluator: TimeControlEvaluator | None = None
) -> AlertEvaluator:
    """
    Build AlertEvaluator from configuration file.

    Handles both old and new configuration formats:
    - Old format: model configs directly in root
    - New format: version + model configs

    Args:
        path: Path to alert configuration YAML file
        valid_device_ids: Set of valid device IDs

    Returns:
        Configured AlertEvaluator instance
    """
    config_dict = ConfigManager.load_yaml_file(path)

    # Parse config_dict to match AlertConfig structure
    alert_config_dict = _parse_alert_config_dict(config_dict)

    # Validate and create AlertConfig
    alert_config = AlertConfig.model_validate(alert_config_dict)

    logger.info(f"Models in config: {list(alert_config.root.keys())}")

    return AlertEvaluator(
        alert_config=alert_config, valid_device_ids=valid_device_ids, time_control_evaluator=time_control_evaluator
    )


def _parse_alert_config_dict(config_dict: dict) -> dict:
    """
    Parse loaded YAML dict into AlertConfig structure.

    Supports two formats:

    Format 1 (New - with version):
        version: "1.0.0"
        TECO_L510:
          default_alerts: [...]
        DAE_PM210:
          default_alerts: [...]

    Format 2 (Old - without version):
        TECO_L510:
          default_alerts: [...]
        DAE_PM210:
          default_alerts: [...]

    Args:
        config_dict: Raw dictionary from YAML file

    Returns:
        Dictionary with structure: {"version": "...", "root": {...}}
    """
    # Check if config has version field
    version = config_dict.get("version", "1.0.0")

    # Extract model configs (everything except 'version')
    root_dict = {k: v for k, v in config_dict.items() if k != "version"}

    # Build final structure
    return {"version": version, "root": root_dict}
