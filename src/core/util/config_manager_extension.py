"""
ConfigManager Extension for Three-Layer Architecture
Adds build_final_register_map method - merges Driver, Pin Mapping, and Instance Override layers
"""

import logging
from typing import Union

from core.schema.driver_schema import ComputedPinDefinition, PhysicalPinDefinition
from core.schema.pin_mapping_schema import PinMapping

logger = logging.getLogger(__name__)

DEFAULT_APPLICATION_CONFIG = {
    "formula": [0, 1, 0],
    "type": "analog",
    "unit": "",
    "precision": 3,
}


class ConfigManagerExtension:
    """
    Three-Layer Configuration Merging
    Integrate this method into ConfigManager class in src/core/util/config_manager.py
    """

    @staticmethod
    def build_final_register_map(
        driver_register_map: dict[str, Union[PhysicalPinDefinition, ComputedPinDefinition]],
        pin_mappings: dict[str, PinMapping],
        instance_pin_overrides: dict[str, dict] | None = None,
    ) -> dict[str, dict]:
        """
        Build final register map by merging three layers.

        Layer 1 (Driver - Hardware Definition):
            - Physical pins: offset, format, readable, writable, description
            - Fixed-spec devices may also include: scale, type, unit, precision, formula
            - Computed pins: type="computed", formula, inputs, output_format

        Layer 2 (Pin Mapping - Model-level Application Definition):
            - name, formula, type, unit, precision (override driver defaults)
            - Only applies to physical pins (AI modules)

        Layer 3 (Instance Override - Instance-specific Adjustments):
            - Any field can be overridden (typically only formula coefficients)

        Merging Priority: Instance Override > Pin Mapping > Driver

        Args:
            driver_register_map: Driver hardware register definitions
            pin_mappings: Model-level pin mappings
            instance_pin_overrides: Instance-specific overrides (optional)

        Returns:
            Final register map compatible with AsyncGenericModbusDevice
        """
        final_map: dict[str, dict] = {}

        # Step 1: Build base from driver register_map
        for pin_name, pin_def in driver_register_map.items():

            # Handle computed fields (GTA_A26A, etc.)
            if isinstance(pin_def, ComputedPinDefinition):
                final_map[pin_name] = {
                    "type": pin_def.type,
                    "formula": pin_def.formula,
                    "inputs": pin_def.inputs,
                    "output_format": pin_def.output_format,
                    "description": pin_def.description or "",
                }
                continue

            # Handle physical registers
            base_config = {
                "offset": pin_def.offset,
                "format": pin_def.format,
                "readable": pin_def.readable,
                "writable": pin_def.writable,
                "description": pin_def.description or "",
                "name": pin_def.description or pin_name,
                "register_type": pin_def.register_type,
            }

            # Check if driver provides fixed-spec fields (Inverter/Power Meter/Sensor)
            # If yes, use driver values; otherwise use defaults (AI Module)
            if pin_def.scale is not None:
                base_config["scale"] = pin_def.scale

            if pin_def.type is not None:
                base_config["type"] = pin_def.type
            else:
                base_config["type"] = DEFAULT_APPLICATION_CONFIG["type"]

            if pin_def.unit is not None:
                base_config["unit"] = pin_def.unit
            else:
                base_config["unit"] = DEFAULT_APPLICATION_CONFIG["unit"]

            if pin_def.precision is not None:
                base_config["precision"] = pin_def.precision
            else:
                base_config["precision"] = DEFAULT_APPLICATION_CONFIG["precision"]

            if pin_def.formula is not None:
                base_config["formula"] = list(pin_def.formula)
            else:
                base_config["formula"] = DEFAULT_APPLICATION_CONFIG["formula"]

            final_map[pin_name] = base_config

        # Step 2: Apply pin_mapping overrides (model-level, only for AI modules)
        for pin_name, pin_mapping in pin_mappings.items():
            if pin_name not in final_map:
                logger.warning(f"Pin mapping defines '{pin_name}' but it's not in driver register_map, skipping")
                continue

            # Skip computed fields (they don't need pin mapping)
            if final_map[pin_name].get("type") == "computed":
                logger.warning(f"Pin mapping for computed field '{pin_name}' is not allowed, skipping")
                continue

            # Directly access model attributes
            if pin_mapping.name is not None:
                final_map[pin_name]["name"] = pin_mapping.name
            if pin_mapping.formula is not None:
                final_map[pin_name]["formula"] = list(pin_mapping.formula)
            if pin_mapping.type is not None:
                final_map[pin_name]["type"] = pin_mapping.type
            if pin_mapping.unit is not None:
                final_map[pin_name]["unit"] = pin_mapping.unit
            if pin_mapping.precision is not None:
                final_map[pin_name]["precision"] = pin_mapping.precision

        # Step 3: Apply instance-specific overrides (highest priority)
        if instance_pin_overrides:
            for pin_name, override_dict in instance_pin_overrides.items():
                if pin_name not in final_map:
                    logger.warning(f"Instance override for '{pin_name}' but pin not in register_map, skipping")
                    continue

                # Override any provided fields
                for field, value in override_dict.items():
                    if field == "formula" and isinstance(value, list):
                        final_map[pin_name]["formula"] = list(value)
                    else:
                        final_map[pin_name][field] = value

        return final_map
