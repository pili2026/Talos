import os
import re

import yaml

from core.schema.constraint_schema import ConstraintConfig, ConstraintConfigSchema, DeviceConfig


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
    def get_device_startup_frequency(config: ConstraintConfigSchema, model: str, slave_id: int) -> float | None:
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

        # Check instance-specific settings
        if device_config.instances:
            instance_config = device_config.instances.get(str(slave_id))
            if instance_config:
                if instance_config.constraints:
                    result.update(instance_config.constraints)
                elif instance_config.use_default_constraints and device_config.default_constraints:
                    result.update(device_config.default_constraints)

        return result

    @staticmethod
    def get_instance_pins_from_schema(config: ConstraintConfigSchema, model: str, slave_id: int) -> dict[str, dict]:
        """
        Pins override policy (Scheme A: baseline + delta):
        - Use model-level pins as baseline: devices[model].pins
        - Apply instance-level overrides: devices[model].instances[slave_id].pins
        - Merge per-pin by fields (override wins)
        """
        device_config = config.devices.get(model)
        if not device_config:
            return {}

        def _to_dict(obj) -> dict:
            if not obj:
                return {}
            if isinstance(obj, dict):
                return dict(obj)
            try:
                return obj.model_dump(exclude_none=True)  # type: ignore[attr-defined]
            except Exception:
                return {}

        # 1) baseline pins at model-level
        base_pins_raw = getattr(device_config, "pins", None)
        base_pins: dict[str, dict] = {}
        for pin_name, pin_cfg in _to_dict(base_pins_raw).items():
            if isinstance(pin_cfg, dict):
                base_pins[pin_name] = dict(pin_cfg)

        # 2) instance pins overrides
        inst_pins: dict[str, dict] = {}
        if device_config.instances:
            instance_config = device_config.instances.get(str(slave_id))
            if instance_config:
                inst_pins_raw = getattr(instance_config, "pins", None)
                for pin_name, pin_cfg in _to_dict(inst_pins_raw).items():
                    if isinstance(pin_cfg, dict):
                        inst_pins[pin_name] = dict(pin_cfg)

        # 3) merge: baseline + override (override wins, per-field)
        if not base_pins and not inst_pins:
            return {}

        out: dict[str, dict] = {k: dict(v) for k, v in base_pins.items()}
        for pin_name, override_cfg in inst_pins.items():
            if pin_name in out and isinstance(out[pin_name], dict):
                merged = dict(out[pin_name])
                merged.update(override_cfg)
                out[pin_name] = merged
            else:
                # allow "new pin" definition at instance level if you want (optional)
                out[pin_name] = dict(override_cfg)

        return out

    @staticmethod
    def get_device_auto_turn_on(config: ConstraintConfigSchema, model: str, slave_id: int) -> bool:
        """Get auto_turn_on setting with priority: instance > model > global."""
        device_config: DeviceConfig | None = config.devices.get(model)

        # Instance level
        if device_config and device_config.instances:
            instance = device_config.instances.get(str(slave_id))
            if instance and instance.initialization and instance.initialization.auto_turn_on is not None:
                return instance.initialization.auto_turn_on

        # Model level
        if device_config and device_config.initialization and device_config.initialization.auto_turn_on is not None:
            return device_config.initialization.auto_turn_on

        # Global level
        if config.global_defaults and config.global_defaults.initialization:
            return config.global_defaults.initialization.auto_turn_on or False

        return False

    @staticmethod
    def _parse_value_by_type(value: str) -> bool | int | float | str:
        if value.lower() in ["true", "false"]:
            return value.lower() == "true"
        if ConfigManager._is_int(value):
            return int(value)
        if ConfigManager._is_float(value):
            return float(value)
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
