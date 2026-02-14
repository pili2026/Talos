"""
Configuration Manager for Talos
Handles business logic layer configuration queries with optional version management support
"""

import logging
import os
import re

import yaml

from core.schema.constraint_schema import ConstraintConfig, ConstraintConfigSchema, DeviceConfig, InstanceConfig
from core.schema.modbus_config_metadata import ConfigSource
from core.util.yaml_manager import YAMLManager

logger = logging.getLogger(__name__)


class ConfigManager:
    """
    Configuration manager with dual-mode support:

    Mode 1 (Legacy): Direct file access without version management
        manager = ConfigManager()
        config = manager.load_constraint_config("config/device_instance.yml")

    Mode 2 (Managed): With YAMLManager for version control and backup
        yaml_mgr = YAMLManager("config")
        manager = ConfigManager(yaml_manager=yaml_mgr)
        config = manager.load_constraint_config_managed()
    """

    def __init__(self, yaml_manager: YAMLManager | None = None):
        """
        Initialize ConfigManager.

        Args:
            yaml_manager: Optional YAMLManager for version-controlled config access.
                         If None, falls back to direct file access (legacy mode).
        """
        self.yaml_manager = yaml_manager
        self._constraint_config: ConstraintConfigSchema | None = None

        if yaml_manager:
            logger.info("[ConfigManager] Initialized with YAMLManager (managed mode)")
        else:
            logger.info("[ConfigManager] Initialized without YAMLManager (legacy mode)")

    # ============================================================================
    # Configuration Loading Methods
    # ============================================================================

    @staticmethod
    def load_yaml_file(path: str) -> dict:
        """
        Load YAML file directly (legacy method).

        Args:
            path: File path to YAML file

        Returns:
            Parsed YAML as dictionary
        """
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    @staticmethod
    def load_constraint_config(config_path: str) -> ConstraintConfigSchema:
        """
        Load and validate constraint configuration (legacy method).

        This is the original method - loads directly from file path without
        version management or backup support.

        Args:
            config_path: Path to device_instance.yml file

        Returns:
            Validated ConstraintConfigSchema
        """
        raw_config: dict = ConfigManager.load_yaml_file(config_path)
        return ConstraintConfigSchema.model_validate(raw_config)

    def load_constraint_config_managed(self) -> ConstraintConfigSchema:
        """
        Load constraint configuration through YAMLManager (managed mode).

        Benefits over legacy load_constraint_config():
        - Automatic metadata tracking (generation, checksum, timestamps)
        - Knows current version and source (cloud/edge/manual)
        - Access to backup/restore functionality

        Returns:
            Validated ConstraintConfigSchema with metadata

        Raises:
            ValueError: If YAMLManager not initialized
            FileNotFoundError: If config file doesn't exist

        Example:
            >>> yaml_mgr = YAMLManager("config")
            >>> manager = ConfigManager(yaml_manager=yaml_mgr)
            >>> config = manager.load_constraint_config_managed()
            >>> print(f"Generation: {config.metadata.generation}")
        """
        if not self.yaml_manager:
            raise ValueError(
                "YAMLManager not initialized. "
                "Use load_constraint_config(path) for legacy mode, "
                "or initialize with ConfigManager(yaml_manager=...)"
            )

        self._constraint_config = self.yaml_manager.read_config("device_instance")
        logger.info(
            f"[ConfigManager] Loaded device_instance config: "
            f"generation={self._constraint_config.metadata.generation}, "
            f"source={self._constraint_config.metadata.config_source}"
        )
        return self._constraint_config

    def save_constraint_config_managed(
        self,
        config: ConstraintConfigSchema | None = None,
        source: ConfigSource = ConfigSource.EDGE,
        modified_by: str | None = None,
    ) -> None:
        """
        Save constraint configuration through YAMLManager (managed mode).

        Automatically handles:
        - Generation increment
        - Checksum calculation
        - Timestamp updates
        - Backup creation
        - Atomic writes

        Args:
            config: Configuration to save. If None, uses last loaded config.
            source: Source of the change (EDGE/CLOUD/MANUAL)
            modified_by: User/system identifier

        Raises:
            ValueError: If YAMLManager not initialized or no config to save

        Example:
            >>> # Load, modify, save
            >>> config = manager.load_constraint_config_managed()
            >>> config.devices["NEW_DEVICE"] = DeviceConfig(...)
            >>> manager.save_constraint_config_managed(
            ...     config,
            ...     source=ConfigSource.EDGE,
            ...     modified_by="jeremy@example.com"
            ... )
        """
        if not self.yaml_manager:
            raise ValueError("YAMLManager not initialized")

        config_to_save = config or self._constraint_config
        if not config_to_save:
            raise ValueError(
                "No config to save. Either pass config parameter or "
                "load config first with load_constraint_config_managed()"
            )

        self.yaml_manager.update_config(
            "device_instance", config_to_save, config_source=source, modified_by=modified_by
        )

        # Update cached config
        self._constraint_config = config_to_save

        logger.info(
            f"[ConfigManager] Saved device_instance config: "
            f"generation={config_to_save.metadata.generation}, "
            f"source={source}, modified_by={modified_by}"
        )

    def get_current_config(self) -> ConstraintConfigSchema | None:
        """
        Get the currently loaded configuration.

        Returns:
            Currently loaded config, or None if no config loaded
        """
        return self._constraint_config

    def reload_constraint_config(self) -> ConstraintConfigSchema:
        """
        Reload constraint configuration from file.

        Useful for detecting external changes to config file.

        Returns:
            Freshly loaded ConstraintConfigSchema

        Raises:
            ValueError: If YAMLManager not initialized
        """
        if not self.yaml_manager:
            raise ValueError("YAMLManager not initialized for reload")

        return self.load_constraint_config_managed()

    # ============================================================================
    # Business Logic Query Methods (unchanged from original)
    # ============================================================================

    @staticmethod
    def parse_env_var_with_default(value: str) -> bool | int | float | str | None:
        """Parse environment variable with default value syntax."""
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
    def get_device_startup_frequency(config: ConstraintConfigSchema, model: str, slave_id: int) -> float | None:
        """
        Retrieve the startup frequency configuration for a device.

        Precedence (higher overrides lower):
        1. Instance level: devices[model].instances[slave_id].initialization.startup_frequency
        2. Model level: devices[model].initialization.startup_frequency
        3. Global level: global_defaults.initialization.startup_frequency

        Args:
            config: Constraint configuration schema
            model: Device model name
            slave_id: Device slave ID

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
        """
        Retrieve instance-level constraint configuration from Schema.

        Args:
            config: Constraint configuration schema
            model: Device model name
            slave_id: Device slave ID

        Returns:
            Dictionary of constraint configurations
        """
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

        pins: dict[str, dict] = instance_config.pins or {}
        if not pins:
            return {}

        cleaned: dict[str, dict] = {}
        for pin_name, override in pins.items():
            if not isinstance(override, dict):
                logger.warning(f"[{model}_{slave_id}] pin override '{pin_name}' is not dict, skip")
                continue

            # Remove None values so they won't overwrite driver defaults
            data = {k: v for k, v in override.items() if v is not None}
            if not data:
                continue
            cleaned[pin_name] = data

        if cleaned:
            logger.debug(f"Instance '{model}_{slave_id}' has {len(cleaned)} pin overrides (cleaned)")
        return cleaned

    @staticmethod
    def get_device_auto_turn_on(config: ConstraintConfigSchema, model: str, slave_id: int) -> bool | None:
        """
        Get auto_turn_on setting with hierarchical precedence.

        Precedence (higher overrides lower):
        1. Instance level: devices[model].instances[slave_id].initialization.auto_turn_on
        2. Model level: devices[model].initialization.auto_turn_on
        3. Global level: global_defaults.initialization.auto_turn_on

        Args:
            config: Constraint configuration schema
            model: Device model name
            slave_id: Device slave ID

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
        """Parse string value to appropriate type."""
        if value.lower() in ["true", "false"]:
            return value.lower() == "true"
        if ConfigManager._is_int(value):
            return int(value)
        if ConfigManager._is_float(value):
            return float(value)
        return value

    @staticmethod
    def _is_int(value: str) -> bool:
        """Check if string can be parsed as integer."""
        try:
            int(value)
            return True
        except ValueError:
            return False

    @staticmethod
    def _is_float(value: str) -> bool:
        """Check if string can be parsed as float."""
        try:
            float(value)
            return True
        except ValueError:
            return False
