from alert_config import AlertConfig
from control_config import ControlConfig
from evaluator.alert_evaluator import AlertEvaluator
from evaluator.control_evaluator import ControlEvaluator
from util.config_manager import ConfigManager


def build_alert_evaluator(path: str, valid_device_ids: set[str]) -> AlertEvaluator:
    config_dict = ConfigManager.load_yaml_file(path)
    alert_config = AlertConfig.model_validate({"root": config_dict})
    return AlertEvaluator(alert_config, valid_device_ids)


def build_control_evaluator(path: str) -> ControlEvaluator:
    config_dict = ConfigManager.load_yaml_file(path)
    control_config = ControlConfig.model_validate({"root": config_dict})
    return ControlEvaluator(control_config)
