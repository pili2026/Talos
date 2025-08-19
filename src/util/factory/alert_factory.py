from alert_config import AlertConfig
from evaluator.alert_evaluator import AlertEvaluator
from util.config_manager import ConfigManager
from util.notifier.base import BaseNotifier
from util.pubsub.base import PubSub
from util.pubsub.subscriber.alert_evaluator_subscriber import AlertEvaluatorSubscriber
from util.pubsub.subscriber.alert_notifier_subscriber import AlertNotifierSubscriber


def build_alert_evaluator(path: str, valid_device_ids: set[str]) -> AlertEvaluator:
    config_dict = ConfigManager.load_yaml_file(path)
    alert_config = AlertConfig.model_validate({"root": config_dict})
    return AlertEvaluator(alert_config, valid_device_ids)


def build_alert_subscriber(
    alert_path: str, pubsub: PubSub, valid_device_ids: set[str], notifier_list: list[BaseNotifier]
) -> tuple[AlertEvaluatorSubscriber, AlertNotifierSubscriber]:
    alert_evaluator: AlertEvaluator = build_alert_evaluator(alert_path, valid_device_ids)
    alert_eval_subscriber = AlertEvaluatorSubscriber(pubsub, alert_evaluator)
    alert_notifier_subscriber = AlertNotifierSubscriber(pubsub, notifier_list)
    return alert_eval_subscriber, alert_notifier_subscriber
