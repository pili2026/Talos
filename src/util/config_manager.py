import os
import re

import yaml


class ConfigManager:

    @staticmethod
    def load_yaml_file(path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    @staticmethod
    def parse_env_var_with_default(value: str) -> bool | int | float | str | None:
        match = re.match(r"\$\{(\w+)(?::-([^\}]*))?\}", value)  # Match ${VAR_NAME:-default} or ${VAR_NAME}
        if not match:
            return value

        var_name = match.group(1)
        default_value = match.group(2)

        resolved_value = os.getenv(var_name) or default_value
        if resolved_value is not None:
            return ConfigManager._parse_value_by_type(resolved_value)
        return None

    @staticmethod
    def _parse_value_by_type(value: str) -> bool | int | float | str:
        if value.lower() in ["true", "false"]:
            return value.lower() == "true"
        elif ConfigManager._is_int(value):
            return int(value)
        elif ConfigManager._is_float(value):
            return float(value)
        else:
            return value

    @staticmethod
    def _is_int(value: str) -> bool:
        try:
            int(value)
            return True
        except ValueError:
            return False

    @staticmethod
    def _is_float(value: str) -> bool:
        try:
            float(value)
            return True
        except ValueError:
            return False

    # TODO: Maybe need move to a separate utility class
    @staticmethod
    def get_instance_constraints(config: dict, model: str, slave_id: int | str) -> dict:
        model_config: dict = config.get(model, {})
        default_constraints: dict = model_config.get("default_constraints", {})
        instance_dict: dict = model_config.get("instances", {})
        instance_config_per_device: dict = instance_dict.get(str(slave_id), {})

        if instance_config_per_device.get("use_default_constraints") or "constraints" not in instance_config_per_device:
            return default_constraints

        return {**default_constraints, **instance_config_per_device["constraints"]}
