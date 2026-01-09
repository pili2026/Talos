"""
ConfigManager Extension for Three-Layer Architecture
Adds build_final_register_map method - merges Driver, Pin Mapping, and Instance Override layers

Supports three pin types:
- PhysicalPinDefinition: hardware register with offset
- ComputedPinDefinition: formula + inputs (type="computed")
- ComposedPinDefinition: composed_of + compose_format (kind="composed")
"""

import logging
from typing import Union

from core.schema.driver_schema import ComposedPinDefinition, ComputedPinDefinition, PhysicalPinDefinition
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

    Layer 1 (Driver - Hardware Definition):
        - Physical pins: offset, format, readable, writable, description
        - Fixed-spec devices may also include: scale, scale_from, type, unit, precision, formula
        - Computed pins: type="computed", formula, inputs, output_format
        - Composed pins: kind="composed", composed_of, compose_format (+ optional scale/scale_from/type/unit/precision)

    Layer 2 (Pin Mapping - Model-level Application Definition):
        - name, formula, type, unit, precision (override driver defaults)
        - Only applies to PHYSICAL pins (AI modules)

    Layer 3 (Instance Override - Instance-specific Adjustments):
        - Any field can be overridden for PHYSICAL pins
        - For COMPOSED pins, only allow safe subset overrides (scale, scale_from, unit, precision, description, name, type)

    Merging Priority: Instance Override > Pin Mapping > Driver
    """

    @staticmethod
    def build_final_register_map(
        driver_register_map: dict[str, Union[PhysicalPinDefinition, ComputedPinDefinition, ComposedPinDefinition]],
        pin_mappings: dict[str, PinMapping],
        instance_pin_overrides: dict[str, dict] | None = None,
    ) -> dict[str, dict]:
        """
        Build final register map by merging three layers.

        Args:
            driver_register_map: Driver hardware register definitions
            pin_mappings: Model-level pin mappings
            instance_pin_overrides: Instance-specific overrides (optional)

        Returns:
            Final register map compatible with AsyncGenericModbusDevice
        """
        final_map: dict[str, dict] = {}

        # =========================
        # Step 1: Base from driver
        # =========================
        for pin_name, pin_def in driver_register_map.items():

            # 1) Computed pins
            if isinstance(pin_def, ComputedPinDefinition):
                cfg = {
                    "type": "computed",
                    "formula": pin_def.formula,
                    "inputs": list(pin_def.inputs),
                    "output_format": pin_def.output_format,
                    "description": pin_def.description or "",
                    "readable": pin_def.readable,
                    "writable": pin_def.writable,
                }
                # Optional fields - only set if not None
                if pin_def.scale is not None:
                    cfg["scale"] = pin_def.scale
                if pin_def.scale_from is not None:
                    cfg["scale_from"] = pin_def.scale_from
                if pin_def.unit is not None:
                    cfg["unit"] = pin_def.unit
                if pin_def.precision is not None:
                    cfg["precision"] = pin_def.precision

                final_map[pin_name] = cfg
                continue

            # 2) Composed pins
            if isinstance(pin_def, ComposedPinDefinition):
                cfg = {
                    "kind": "composed",
                    "composed_of": list(pin_def.composed_of),
                    "compose_format": pin_def.compose_format,
                    "readable": pin_def.readable,
                    "writable": pin_def.writable,
                    "description": pin_def.description or "",
                    "name": pin_def.description or pin_name,
                    "type": pin_def.type or DEFAULT_APPLICATION_CONFIG["type"],
                    "unit": pin_def.unit or DEFAULT_APPLICATION_CONFIG["unit"],
                    "precision": (
                        pin_def.precision if pin_def.precision is not None else DEFAULT_APPLICATION_CONFIG["precision"]
                    ),
                    "formula": DEFAULT_APPLICATION_CONFIG["formula"],
                }

                # Optional fields - only set if not None
                if pin_def.scale is not None:
                    cfg["scale"] = pin_def.scale
                if pin_def.scale_from is not None:
                    cfg["scale_from"] = pin_def.scale_from

                final_map[pin_name] = cfg
                continue

            # 3) Physical pins
            base_config: dict = {
                "offset": pin_def.offset,
                "format": pin_def.format,
                "readable": pin_def.readable,
                "writable": pin_def.writable,
                "description": pin_def.description or "",
                "name": pin_def.description or pin_name,
                "type": pin_def.type if pin_def.type is not None else DEFAULT_APPLICATION_CONFIG["type"],
                "unit": pin_def.unit if pin_def.unit is not None else DEFAULT_APPLICATION_CONFIG["unit"],
                "precision": (
                    pin_def.precision if pin_def.precision is not None else DEFAULT_APPLICATION_CONFIG["precision"]
                ),
                "formula": (
                    list(pin_def.formula) if pin_def.formula is not None else DEFAULT_APPLICATION_CONFIG["formula"]
                ),
            }

            # Optional fields
            if pin_def.register_type is not None:
                base_config["register_type"] = pin_def.register_type
            if pin_def.scale is not None:
                base_config["scale"] = pin_def.scale
            if pin_def.scale_from is not None:
                base_config["scale_from"] = pin_def.scale_from
            if pin_def.bit is not None:
                base_config["bit"] = pin_def.bit

            final_map[pin_name] = base_config

        # ==========================================
        # Step 2: Apply pin_mapping overrides (PHYSICAL only)
        # ==========================================
        for pin_name, pin_mapping in pin_mappings.items():
            if pin_name not in final_map:
                logger.warning(f"Pin mapping defines '{pin_name}' but it's not in driver register_map, skipping")
                continue

            # Skip computed / composed fields
            if final_map[pin_name].get("type") == "computed":
                logger.warning(f"Pin mapping for computed field '{pin_name}' is not allowed, skipping")
                continue
            if final_map[pin_name].get("kind") == "composed":
                logger.warning(f"Pin mapping for composed field '{pin_name}' is not allowed, skipping")
                continue

            # Apply overrides
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

        # ==========================================
        # Step 3: Apply instance-specific overrides
        # ==========================================
        if instance_pin_overrides:
            for pin_name, override_dict in instance_pin_overrides.items():
                if pin_name not in final_map:
                    logger.warning(f"Instance override for '{pin_name}' but pin not in register_map, skipping")
                    continue

                # Computed: generally should not be overridden here (unless you explicitly want it)
                if final_map[pin_name].get("type") == "computed":
                    logger.warning(f"Instance override for computed field '{pin_name}' is not allowed, skipping")
                    continue

                # Composed: allow only safe subset
                if final_map[pin_name].get("kind") == "composed":
                    allowed = {"scale", "scale_from", "unit", "precision", "description", "name", "type"}
                    for field, value in override_dict.items():
                        if field not in allowed:
                            logger.warning(
                                f"Override field '{field}' for composed pin '{pin_name}' is not allowed, skipping"
                            )
                            continue
                        final_map[pin_name][field] = value
                    continue

                # Physical: allow all fields
                for field, value in override_dict.items():
                    if field == "formula" and isinstance(value, list):
                        final_map[pin_name]["formula"] = list(value)
                    else:
                        final_map[pin_name][field] = value

        return final_map
