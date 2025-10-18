"""
Configuration Data Access Layer

Responsible for loading and managing Talos configuration files.
Provides configuration query interfaces.
"""

import yaml
from pathlib import Path
from typing import Any
import logging

logger = logging.getLogger(__name__)


class ConfigRepository:
    """
    Configuration data access layer.

    Responsibilities:
    - Load YAML configuration files
    - Parse device configurations
    - Provide configuration query methods
    """

    _instance = None
    _initialized = False

    def __new__(cls):
        """Implement the singleton pattern"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize the Config Repository"""
        if not self._initialized:
            self._modbus_config: dict[str, Any] = {}
            self._instance_config: dict[str, Any] = {}
            self._device_map: dict[str, dict[str, Any]] = {}
            self._model_definitions: dict[str, dict[str, Any]] = {}
            self._parameter_case_map: dict[str, dict[str, str]] = {}
            self.__class__._initialized = True

    def initialize_sync(self):
        """
        Synchronously initialize configuration loading.

        Loads all required configuration files.
        """
        base_path = Path(__file__).parent.parent.parent.parent / "res"

        try:
            # Load the Modbus device list
            modbus_path = base_path / "modbus_device.yml"  # TODO: Use attribute instead hardcoded path
            if modbus_path.exists():
                self._modbus_config = self._load_yaml(modbus_path)
                logger.info(f"Loaded modbus device config from {modbus_path}")
            else:
                logger.warning(f"Modbus config not found: {modbus_path}")

            # Load device instance configuration (constraints)
            instance_path = base_path / "device_instance_config.yml"
            if instance_path.exists():
                self._instance_config = self._load_yaml(instance_path)
                logger.info(f"Loaded instance config from {instance_path}")
            else:
                logger.warning(f"Instance config not found: {instance_path}")

            # Load all driver files (register_map definitions)
            self._load_driver_files(base_path)

            # Build device mapping
            self._build_device_map()

        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            raise

    def _load_yaml(self, file_path: Path) -> dict[str, Any]:
        """
        Load a YAML file.

        Args:
            file_path: Path to the file.

        Returns:
            dict: Parsed configuration.
        """
        if not file_path.exists():
            logger.warning(f"Config file not found: {file_path}")
            return {}

        with open(file_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _load_driver_files(self, base_path: Path):
        """
        Load all driver files.

        Automatically handles:
        1. Distinguishing sensor types (thermometer) vs. Modbus register types (holding)
        2. Converting formula to scale
        """
        devices = self._modbus_config.get("devices", [])

        for device in devices:
            model = device.get("model")
            model_file = device.get("model_file")

            if not model or not model_file:
                continue

            if model in self._model_definitions:
                continue

            # Load the driver file
            driver_path = base_path / model_file
            if driver_path.exists():
                model_def = self._load_yaml(driver_path)

                #  Get global Modbus register type
                global_register_type = model_def.get("register_type", "holding")

                #  Normalize register_map
                register_map = model_def.get("register_map", {})
                normalized_register_map = {}

                for param_name, param_def in register_map.items():
                    normalized_param_def = param_def.copy()

                    #  Handle the 'type' field (sensor type vs. Modbus register type)
                    if "type" in normalized_param_def:
                        param_type = normalized_param_def["type"]

                        # If 'type' is a Modbus register type, keep it
                        if param_type in ["holding", "input"]:
                            # This is a Modbus register type — OK
                            pass
                        else:
                            # This is a sensor type (thermometer, pressure, flow_meter, etc.)
                            # Save it as sensor_type and use the global register_type
                            normalized_param_def["sensor_type"] = param_type
                            normalized_param_def["type"] = global_register_type

                            logger.debug(
                                f"[CONFIG] {param_name}: sensor_type='{param_type}', register_type='{global_register_type}'"
                            )
                    else:
                        # If 'type' not specified, use the global register_type
                        normalized_param_def["type"] = global_register_type

                    #  Handle the 'formula' field
                    # formula format: [offset_value, scale, ...]
                    if "formula" in normalized_param_def and "scale" not in normalized_param_def:
                        formula = normalized_param_def["formula"]
                        if isinstance(formula, list) and len(formula) >= 2:
                            offset_value = formula[0]
                            scale = formula[1]

                            # Convert to standard 'scale' and 'offset_value'
                            normalized_param_def["scale"] = scale
                            normalized_param_def["offset_value"] = offset_value

                            logger.debug(
                                f"[CONFIG] {param_name}: formula={formula} -> scale={scale}, offset_value={offset_value}"
                            )

                    #  Ensure 'scale' exists (even without formula)
                    if "scale" not in normalized_param_def:
                        normalized_param_def["scale"] = 1.0

                    if "offset_value" not in normalized_param_def:
                        normalized_param_def["offset_value"] = 0.0

                    normalized_register_map[param_name] = normalized_param_def

                # Update model_def
                model_def["register_map"] = normalized_register_map

                self._model_definitions[model] = model_def
                logger.info(
                    f"Loaded driver for {model} from {driver_path}, normalized {len(normalized_register_map)} parameters"
                )
            else:
                logger.warning(f"Driver file not found: {driver_path}")
                self._model_definitions[model] = {}

    def _build_device_map(self):
        """Build the device mapping table"""
        devices = self._modbus_config.get("devices", [])

        for device in devices:
            model = device.get("model")
            slave_id = str(device.get("slave_id"))
            device_type = device.get("type", "unknown")
            port = device.get("port", "/dev/ttyUSB0")

            device_id = f"{model}_{slave_id}"

            # Get register_map from the driver file
            model_def = self._model_definitions.get(model, {})
            register_map = model_def.get("register_map", {})

            #  Build a case-insensitive parameter mapping
            param_case_map = {}
            for param_name in register_map.keys():
                param_lower = param_name.lower()
                param_case_map[param_lower] = param_name  # lowercase -> original case

            self._parameter_case_map[device_id] = param_case_map

            # Get constraints from device_instance_config.yml
            model_config = self._instance_config.get(model, {})
            default_constraints = model_config.get("default_constraints", {})
            instances = model_config.get("instances", {})
            instance_config = instances.get(slave_id, {})
            instance_constraints = instance_config.get("constraints", {})

            final_constraints = {**default_constraints, **instance_constraints}

            # Get initialization settings
            global_init = self._instance_config.get("global_defaults", {}).get("initialization", {})
            model_init = model_config.get("initialization", {})
            instance_init = instance_config.get("initialization", {})
            final_init = {**global_init, **model_init, **instance_init}

            self._device_map[device_id] = {
                "device_id": device_id,
                "model": model,
                "slave_id": slave_id,
                "type": device_type,
                "port": port,
                "register_map": register_map,
                "available_parameters": list(register_map.keys()),
                "constraints": final_constraints,
                "initialization": final_init,
                "description": f"{model} (Slave ID: {slave_id})",
            }

        logger.info(f"Built device map with {len(self._device_map)} devices")

    def _normalize_parameter_name(self, device_id: str, parameter: str) -> str | None:
        """
        Normalize the parameter name (case-insensitive lookup).

        Args:
            device_id: Device identifier
            parameter: Parameter name provided by the user (any case)

        Returns:
            Optional[str]: The original parameter name (as in driver files). Returns None if not found.

        Example:
            _normalize_parameter_name("SD400_3", "AINXX")  → "AInXX"
            _normalize_parameter_name("SD400_3", "ainxx")  → "AInXX"
            _normalize_parameter_name("SD400_3", "AInXX")  → "AInXX"
        """
        param_case_map = self._parameter_case_map.get(device_id, {})
        param_lower = parameter.lower()
        return param_case_map.get(param_lower)

    def get_all_device_configs(self) -> dict[str, dict[str, Any]]:
        """
        Get all device configurations.

        Returns:
            dict: A dictionary of device configurations.
        """
        return self._device_map.copy()

    def get_device_config(self, device_id: str) -> dict[str, Any] | None:
        """
        Get configuration for a specific device.

        Args:
            device_id: Device identifier (format: MODEL_SLAVEID)

        Returns:
            Optional[dict]: Device configuration, or None if not found.
        """
        return self._device_map.get(device_id)

    def get_all_models(self) -> list[str]:
        """
        Get a list of all device models.

        Returns:
            list[str]: List of model names.
        """
        return list(self._model_definitions.keys())

    def get_model_definition(self, model: str) -> dict[str, Any] | None:
        """
        Get the definition for a device model.

        Args:
            model: Model name.

        Returns:
            Optional[dict]: Model definition.
        """
        return self._model_definitions.get(model)

    def get_parameter_definition(self, device_id: str, parameter: str) -> dict[str, Any] | None:
        """
        Get the parameter definition (case-insensitive).

        Args:
            device_id: Device identifier.
            parameter: Parameter name (case-insensitive).

        Returns:
            dict | None: Parameter definition, or None if it doesn't exist.
        """
        device_config = self.get_device_config(device_id)
        if not device_config:
            return None

        #  Normalize the parameter name
        normalized_param = self._normalize_parameter_name(device_id, parameter)
        if not normalized_param:
            logger.warning(f"Parameter '{parameter}' not found for device {device_id} (case-insensitive)")
            return None

        register_map = device_config.get("register_map", {})
        return register_map.get(normalized_param)

    def get_parameter_constraints(self, device_id: str, parameter: str) -> dict[str, float] | None:
        """
        Get parameter constraints (case-insensitive).

        Args:
            device_id: Device identifier.
            parameter: Parameter name (case-insensitive).

        Returns:
            Optional[Dict]: Constraint definition like {"min": x, "max": y}
        """
        device_config = self.get_device_config(device_id)
        if not device_config:
            return None

        #  Normalize the parameter name
        normalized_param = self._normalize_parameter_name(device_id, parameter)
        if not normalized_param:
            return None

        constraints = device_config.get("constraints", {})
        return constraints.get(normalized_param)
