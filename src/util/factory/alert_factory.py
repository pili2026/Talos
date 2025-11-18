# src/util/factory/alert_factory.py
from alert_config import AlertConfig
from evaluator.alert_evaluator import AlertEvaluator
from model.enum.alert_enum import AlertSeverity
from schema.notifier_schema import NotificationConfigSchema, RoutingRule
from util.config_manager import ConfigManager
from util.notifier.base import BaseNotifier
from util.pubsub.base import PubSub
from util.pubsub.subscriber.alert_evaluator_subscriber import AlertEvaluatorSubscriber
from util.pubsub.subscriber.alert_notifier_subscriber import AlertNotifierSubscriber


def build_alert_subscriber(
    alert_path: str,
    pubsub: PubSub,
    valid_device_ids: set[str],
    notifier_list: list[BaseNotifier],
    notifier_config_schema: NotificationConfigSchema,
) -> tuple[AlertEvaluatorSubscriber, AlertNotifierSubscriber]:
    alert_evaluator: AlertEvaluator = build_alert_evaluator(alert_path, valid_device_ids)
    alert_eval_subscriber = AlertEvaluatorSubscriber(pubsub, alert_evaluator)

    routing_rule_dict: dict[AlertSeverity, RoutingRule] = notifier_config_schema.strategy.routing

    alert_notifier_subscriber = AlertNotifierSubscriber(
        pubsub=pubsub,
        notifier_list=notifier_list,
        routing_rules=routing_rule_dict,
        config_schema=notifier_config_schema,
    )
    return alert_eval_subscriber, alert_notifier_subscriber


def build_alert_evaluator(path: str, valid_device_ids: set[str]) -> AlertEvaluator:
    config_dict = ConfigManager.load_yaml_file(path)
    alert_config = AlertConfig.model_validate({"root": config_dict})
    return AlertEvaluator(alert_config, valid_device_ids)
