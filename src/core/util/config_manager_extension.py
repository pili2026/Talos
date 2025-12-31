"""
ConfigManager Extension for Three-Layer Architecture
Adds build_final_register_map method - merges Driver, Pin Mapping, and Instance Override layers
"""

import logging

from core.schema.driver_schema import DriverPinDefinition
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
        driver_register_map: dict[str, DriverPinDefinition],
        pin_mappings: dict[str, PinMapping],
        instance_pin_overrides: dict[str, dict] | None = None,
    ) -> dict[str, dict]:
        """
        Build final register map by merging three layers.

        Layer 1 (Driver - Hardware Definition):
            - offset, format, readable, writable, description

        Layer 2 (Pin Mapping - Model-level Application Definition):
            - name, formula, type, unit, precision (override driver defaults)

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
            # Build base register map entry with hardware layer only
            final_map[pin_name] = {
                "offset": pin_def.offset,
                "format": pin_def.format,
                "readable": pin_def.readable,
                "writable": pin_def.writable,
                "description": pin_def.description or "",
                "name": pin_def.description or pin_name,
                **DEFAULT_APPLICATION_CONFIG,
            }

        # Step 2: Apply pin_mapping overrides (model-level)
        for pin_name, pin_mapping in pin_mappings.items():
            if pin_name not in final_map:
                logger.warning(f"Pin mapping defines '{pin_name}' but it's not in driver register_map, skipping")
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
