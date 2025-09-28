import os
import re

import yaml

from schema.constraint_schema import ConstraintConfig, ConstraintConfigSchema


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
    def load_constraint_config(config_path: str) -> ConstraintConfigSchema:
        """Load and validate constraint configuration"""
        raw_config = ConfigManager.load_yaml_file(config_path)
        return ConstraintConfigSchema(**raw_config)

    @staticmethod
    def _get_device_startup_frequency(config: ConstraintConfigSchema, model: str, slave_id: int) -> float | None:
        """Retrieve the startup frequency configuration for a device"""
        # 1. Check instance settings
        device_config = config.devices.get(model)
        if device_config and device_config.instances:
            instance_config = device_config.instances.get(str(slave_id))
            if (
                instance_config
                and instance_config.initialization
                and instance_config.initialization.startup_frequency is not None
            ):
                return instance_config.initialization.startup_frequency

        # 2. Check model-level settings
        if (
            device_config
            and device_config.initialization
            and device_config.initialization.startup_frequency is not None
        ):
            return device_config.initialization.startup_frequency

        # 3. Check global defaults
        if (
            config.global_defaults
            and config.global_defaults.initialization
            and config.global_defaults.initialization.startup_frequency is not None
        ):
            return config.global_defaults.initialization.startup_frequency

        return None

    @staticmethod
    def get_instance_constraints_from_schema(
        config: ConstraintConfigSchema, model: str, slave_id: int
    ) -> dict[str, ConstraintConfig]:
        """Retrieve instance-level constraint configuration from Schema"""
        device_config = config.devices.get(model)
        if not device_config:
            return {}

        result: dict[str, ConstraintConfig] = {}

        # Retrieve default constraints (already ConstraintConfig objects)
        if device_config.default_constraints:
            result.update(device_config.default_constraints)

        # Check instance-specific settings
        if device_config.instances:
            instance_config = device_config.instances.get(str(slave_id))
            if instance_config:
                if instance_config.use_default_constraints:
                    # Use default constraints (result already contains default_constraints)
                    pass
                elif instance_config.constraints:
                    # Override with specific constraints (already ConstraintConfig objects)
                    result.update(instance_config.constraints)

        return result

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
