import logging
import os
import re

import yaml

from core.schema.constraint_schema import ConstraintConfig, ConstraintConfigSchema, DeviceConfig, InstanceConfig

logger = logging.getLogger(__name__)


class ConfigManager:

    @staticmethod
    def load_yaml_file(path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    @staticmethod
    def parse_env_var_with_default(value: str) -> bool | int | float | str | None:
        match = re.match(r"\$\{(\w+)(?::-([^\}]*))?\}", value)
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
        """
        Retrieve the startup frequency configuration for a device.

        Precedence (higher overrides lower):
        1. Instance level: devices[model].instances[slave_id].initialization.startup_frequency
        2. Model level: devices[model].initialization.startup_frequency
        3. Global level: global_defaults.initialization.startup_frequency

        Returns:
            float | None: Startup frequency in Hz, or None if not configured at any level
        """
        device_config: DeviceConfig | None = config.devices.get(model)

        # 1. Check instance settings
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
        device_config: DeviceConfig | None = config.devices.get(model)
        if not device_config:
            logger.warning(
                f"Model '{model}' not found in config.devices. " f"Available models={list(config.devices.keys())}"
            )
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
        Get instance-specific pin overrides.

        Layer 3 (Instance Override) in the three-layer architecture:
        - This method only returns instance-level pin overrides
        - Model-level baseline is now in pin_mapping (Layer 2)
        - Hardware definition is in driver (Layer 1)

        Args:
            config: Constraint configuration schema
            model: Device model name
            slave_id: Device slave ID

        Returns:
            Dictionary of pin overrides for this specific instance
        """
        device_config: DeviceConfig | None = config.devices.get(model)
        if not device_config:
            logger.debug(f"Model '{model}' not found in config.devices")
            return {}

        # Only get instance-specific overrides
        if not device_config.instances:
            logger.debug(f"Model '{model}' has no instances defined")
            return {}

        instance_config: InstanceConfig | None = device_config.instances.get(str(slave_id))
        if not instance_config:
            logger.debug(f"Instance '{model}_{slave_id}' has no specific config")
            return {}

        # Return instance pins directly (no need for getattr)
        if instance_config.pins:
            logger.debug(f"Instance '{model}_{slave_id}' has {len(instance_config.pins)} pin overrides")
            return dict(instance_config.pins)

        return {}

    @staticmethod
    def get_device_auto_turn_on(config: ConstraintConfigSchema, model: str, slave_id: int) -> bool | None:
        """
        Get auto_turn_on setting with hierarchical precedence.

        Precedence (higher overrides lower):
        1. Instance level: devices[model].instances[slave_id].initialization.auto_turn_on
        2. Model level: devices[model].initialization.auto_turn_on
        3. Global level: global_defaults.initialization.auto_turn_on

        Returns:
            bool | None:
                - True: Should auto turn on device
                - False: Should NOT auto turn on (explicitly disabled)
                - None: Not configured at any level

        Example:
            >>> # Model has auto_turn_on=True, instance doesn't specify
            >>> get_device_auto_turn_on(config, "TECO_VFD", 3)
            True  # Inherits from model

            >>> # Instance explicitly sets auto_turn_on=False
            >>> get_device_auto_turn_on(config, "TECO_VFD", 4)
            False  # Overrides model setting
        """
        device_config: DeviceConfig | None = config.devices.get(model)

        # Instance level (highest priority)
        if device_config and device_config.instances:
            instance = device_config.instances.get(str(slave_id))
            if instance and instance.initialization and instance.initialization.auto_turn_on is not None:
                return instance.initialization.auto_turn_on

        # Model level
        if device_config and device_config.initialization and device_config.initialization.auto_turn_on is not None:
            return device_config.initialization.auto_turn_on

        # Global level (lowest priority)
        if (
            config.global_defaults
            and config.global_defaults.initialization
            and config.global_defaults.initialization.auto_turn_on is not None
        ):
            return config.global_defaults.initialization.auto_turn_on

        return None

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
