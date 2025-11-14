"""
Computed Field Processor for handling virtual/computed fields in device drivers.
Processes computed fields defined in YAML driver configuration.
"""

import logging
from typing import Any

from util.register_formula import get_formula

logger = logging.getLogger("ComputedFieldProcessor")


class ComputedFieldProcessor:
    """
    Processor for computed fields defined in driver YAML.

    Computed fields are virtual fields that are calculated from one or more
    physical register values using a formula.
    """

    def __init__(self, register_map: dict[str, dict[str, Any]]):
        """
        Initialize the computed field processor.

        Args:
            register_map: Register map from driver YAML configuration.
        """
        self.register_map = register_map
        self.computed_fields = self._parse_computed_fields()

    def compute(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """
        Compute all computed fields based on raw data.

        Args:
            raw_data: Raw register values.

        Returns:
            Dictionary with both raw data and computed values.
        """
        if not self.computed_fields:
            # No computed fields, return raw data as-is
            return raw_data

        result = raw_data.copy()

        for field_name, spec in self.computed_fields.items():
            try:
                computed_value = self._compute_single_field(field_name, spec, raw_data)
                result[field_name] = computed_value
                logger.debug(f"Computed {field_name} = {computed_value}")
            except Exception as e:
                logger.error(f"Error computing {field_name}: {e}")
                result[field_name] = None

        return result

    def has_computed_fields(self) -> bool:
        """Check if there are any computed fields."""
        return len(self.computed_fields) > 0

    def _parse_computed_fields(self) -> dict[str, dict[str, Any]]:
        """
        Parse computed fields from register map.

        Returns:
            Dictionary of computed field specifications.
        """
        computed = {}
        for name, spec in self.register_map.items():
            if spec.get("type") == "computed":
                computed[name] = spec
                logger.debug(f"Found computed field: {name} = {spec.get('formula')}({spec.get('inputs')})")
        return computed

    def _compute_single_field(self, field_name: str, spec: dict[str, Any], raw_data: dict[str, Any]) -> Any:
        """
        Compute a single computed field.

        Args:
            field_name: Name of the computed field.
            spec: Field specification from YAML.
            raw_data: Raw register values.

        Returns:
            Computed value.
        """
        formula_name: str = spec.get("formula")
        if not formula_name:
            logger.warning(f"[{field_name}] No formula specified")
            return None

        formula_func = get_formula(formula_name)
        if not formula_func:
            logger.warning(f"[{field_name}] Unknown formula: {formula_name}")
            return None

        input_names = spec.get("inputs", [])
        if not input_names:
            logger.warning(f"[{field_name}] No inputs specified")
            return None

        # Collect input values
        input_values = []
        for input_name in input_names:
            value = raw_data.get(input_name)
            input_values.append(value)

        # Execute formula
        params = spec.get("params", {})
        if params:
            return formula_func(*input_values, **params)
        else:
            return formula_func(*input_values)
