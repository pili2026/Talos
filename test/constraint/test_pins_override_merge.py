"""
Tests for ConfigManagerExtension - Three-Layer Configuration Merging
"""

import logging

import pytest

from src.core.schema.driver_schema import DriverPinDefinition
from src.core.schema.pin_mapping_schema import PinMapping
from src.core.util.config_manager_extension import ConfigManagerExtension


def test_build_final_register_map_layer1_only_driver():
    """
    Test Layer 1 only: Driver hardware definition
    Should create register map with hardware + default application config
    """
    driver_register_map = {
        "AIn01": DriverPinDefinition(
            offset=0, format="i16", readable=True, writable=False, description="Analog Input 01"
        ),
        "AIn02": DriverPinDefinition(
            offset=1, format="i16", readable=True, writable=False, description="Analog Input 02"
        ),
    }

    result = ConfigManagerExtension.build_final_register_map(
        driver_register_map=driver_register_map, pin_mappings={}, instance_pin_overrides=None
    )

    # Check hardware layer
    assert result["AIn01"]["offset"] == 0
    assert result["AIn01"]["format"] == "i16"
    assert result["AIn01"]["readable"] is True
    assert result["AIn01"]["writable"] is False

    # Check default application layer
    assert result["AIn01"]["formula"] == [0, 1, 0]
    assert result["AIn01"]["type"] == "analog"
    assert result["AIn01"]["unit"] == ""
    assert result["AIn01"]["precision"] == 3
    assert result["AIn01"]["name"] == "Analog Input 01"


def test_build_final_register_map_layer2_pin_mapping_override():
    """
    Test Layer 2: Pin Mapping overrides driver defaults
    """
    driver_register_map = {
        "AIn01": DriverPinDefinition(
            offset=0, format="i16", readable=True, writable=False, description="Analog Input 01"
        ),
    }

    pin_mappings = {
        "AIn01": PinMapping(name="Temp1", formula=[0, 0.01220703125, 0.0], type="thermometer", unit="°C", precision=2),
    }

    result = ConfigManagerExtension.build_final_register_map(
        driver_register_map=driver_register_map, pin_mappings=pin_mappings, instance_pin_overrides=None
    )

    # Check pin mapping overrides
    assert result["AIn01"]["name"] == "Temp1"
    assert result["AIn01"]["formula"] == [0, 0.01220703125, 0.0]
    assert result["AIn01"]["type"] == "thermometer"
    assert result["AIn01"]["unit"] == "°C"
    assert result["AIn01"]["precision"] == 2

    # Check hardware layer unchanged
    assert result["AIn01"]["offset"] == 0
    assert result["AIn01"]["format"] == "i16"


def test_build_final_register_map_layer3_instance_override():
    """
    Test Layer 3: Instance-specific overrides (highest priority)
    """
    driver_register_map = {
        "AIn01": DriverPinDefinition(
            offset=0, format="i16", readable=True, writable=False, description="Analog Input 01"
        ),
    }

    pin_mappings = {
        "AIn01": PinMapping(name="Temp1", formula=[0, 0.01220703125, 0.0], type="thermometer", unit="°C", precision=2),
    }

    instance_pin_overrides = {"AIn01": {"formula": [0, 0.01220703125, -1.5]}}

    result = ConfigManagerExtension.build_final_register_map(
        driver_register_map=driver_register_map,
        pin_mappings=pin_mappings,
        instance_pin_overrides=instance_pin_overrides,
    )

    # Check instance override (highest priority)
    assert result["AIn01"]["formula"] == [0, 0.01220703125, -1.5]

    # Check pin mapping fields still applied
    assert result["AIn01"]["name"] == "Temp1"
    assert result["AIn01"]["type"] == "thermometer"
    assert result["AIn01"]["unit"] == "°C"
    assert result["AIn01"]["precision"] == 2


def test_build_final_register_map_three_layer_priority():
    """
    Test priority: Instance Override > Pin Mapping > Driver
    """
    driver_register_map = {
        "AIn01": DriverPinDefinition(
            offset=0, format="i16", readable=True, writable=False, description="Analog Input 01"
        ),
        "AIn02": DriverPinDefinition(
            offset=1, format="i16", readable=True, writable=False, description="Analog Input 02"
        ),
    }

    pin_mappings = {
        "AIn01": PinMapping(name="Temp1", formula=[0, 0.01220703125, 0.0], type="thermometer", unit="°C", precision=2),
        "AIn02": PinMapping(name="Temp2", formula=[0, 0.01220703125, 0.0], type="thermometer", unit="°C", precision=2),
    }

    instance_pin_overrides = {"AIn01": {"formula": [0, 0.01220703125, -1.5]}}

    result = ConfigManagerExtension.build_final_register_map(
        driver_register_map=driver_register_map,
        pin_mappings=pin_mappings,
        instance_pin_overrides=instance_pin_overrides,
    )

    # AIn01: Instance override applied
    assert result["AIn01"]["formula"] == [0, 0.01220703125, -1.5]
    assert result["AIn01"]["name"] == "Temp1"

    # AIn02: Only pin mapping applied (no instance override)
    assert result["AIn02"]["formula"] == [0, 0.01220703125, 0.0]
    assert result["AIn02"]["name"] == "Temp2"


def test_build_final_register_map_partial_pin_mapping_override():
    """
    Test partial override: Only some fields in pin mapping
    """
    driver_register_map = {
        "AIn01": DriverPinDefinition(
            offset=0, format="i16", readable=True, writable=False, description="Analog Input 01"
        ),
    }

    pin_mappings = {
        "AIn01": PinMapping(
            name="Temp1",
            formula=[0, 0.01220703125, 0.0],
            # type, unit, precision not provided -> should use defaults
        ),
    }

    result = ConfigManagerExtension.build_final_register_map(
        driver_register_map=driver_register_map, pin_mappings=pin_mappings, instance_pin_overrides=None
    )

    # Provided fields
    assert result["AIn01"]["name"] == "Temp1"
    assert result["AIn01"]["formula"] == [0, 0.01220703125, 0.0]

    # Default fields (not overridden)
    assert result["AIn01"]["type"] == "analog"
    assert result["AIn01"]["unit"] == ""
    assert result["AIn01"]["precision"] == 3


def test_build_final_register_map_unknown_pin_in_mapping_warns(caplog):
    """
    Test warning when pin mapping references unknown pin
    """
    caplog.set_level(logging.WARNING)

    driver_register_map = {
        "AIn01": DriverPinDefinition(
            offset=0, format="i16", readable=True, writable=False, description="Analog Input 01"
        ),
    }

    pin_mappings = {
        "AIn01": PinMapping(name="Temp1"),
        "AIn99": PinMapping(name="Unknown"),  # Unknown pin
    }

    result = ConfigManagerExtension.build_final_register_map(
        driver_register_map=driver_register_map, pin_mappings=pin_mappings, instance_pin_overrides=None
    )

    # Valid pin exists
    assert "AIn01" in result

    # Unknown pin skipped
    assert "AIn99" not in result

    # Warning logged
    assert "AIn99" in caplog.text
    assert "not in driver register_map" in caplog.text


def test_build_final_register_map_unknown_pin_in_instance_override_warns(caplog):
    """
    Test warning when instance override references unknown pin
    """
    caplog.set_level(logging.WARNING)

    driver_register_map = {
        "AIn01": DriverPinDefinition(
            offset=0, format="i16", readable=True, writable=False, description="Analog Input 01"
        ),
    }

    instance_pin_overrides = {"AIn99": {"formula": [0, 2, 0]}}  # Unknown pin

    result = ConfigManagerExtension.build_final_register_map(
        driver_register_map=driver_register_map, pin_mappings={}, instance_pin_overrides=instance_pin_overrides
    )

    # Valid pin exists
    assert "AIn01" in result

    # Unknown pin skipped
    assert "AIn99" not in result

    # Warning logged
    assert "AIn99" in caplog.text
    assert "not in register_map" in caplog.text


def test_build_final_register_map_formula_list_copy():
    """
    Test that formula list is copied, not referenced
    """
    driver_register_map = {
        "AIn01": DriverPinDefinition(
            offset=0, format="i16", readable=True, writable=False, description="Analog Input 01"
        ),
    }

    original_formula = [0, 0.01220703125, 0.0]
    pin_mappings = {
        "AIn01": PinMapping(formula=original_formula),
    }

    result = ConfigManagerExtension.build_final_register_map(
        driver_register_map=driver_register_map, pin_mappings=pin_mappings, instance_pin_overrides=None
    )

    # Modify result formula
    result["AIn01"]["formula"][2] = -999.0

    # Original should be unchanged
    assert original_formula == [0, 0.01220703125, 0.0]


def test_build_final_register_map_empty_inputs():
    """
    Test with empty pin mappings and no instance overrides
    """
    driver_register_map = {
        "AIn01": DriverPinDefinition(
            offset=0, format="i16", readable=True, writable=False, description="Analog Input 01"
        ),
    }

    result = ConfigManagerExtension.build_final_register_map(
        driver_register_map=driver_register_map, pin_mappings={}, instance_pin_overrides=None
    )

    # Should still work with defaults
    assert "AIn01" in result
    assert result["AIn01"]["formula"] == [0, 1, 0]
    assert result["AIn01"]["name"] == "Analog Input 01"


def test_build_final_register_map_bat08_real_world_scenario():
    """
    Test real-world BAT08 scenario with all three layers
    """
    # Layer 1: Driver (hardware)
    driver_register_map = {
        "AIn01": DriverPinDefinition(offset=0, format="i16", readable=True, writable=False),
        "AIn02": DriverPinDefinition(offset=1, format="i16", readable=True, writable=False),
        "AIn03": DriverPinDefinition(offset=2, format="i16", readable=True, writable=False),
    }

    # Layer 2: Pin Mapping (model-level baseline)
    pin_mappings = {
        "AIn01": PinMapping(name="Temp1", formula=[0, 0.01220703125, 0.0], type="thermometer", unit="°C", precision=2),
        "AIn02": PinMapping(name="Temp2", formula=[0, 0.01220703125, 0.0], type="thermometer", unit="°C", precision=2),
        "AIn03": PinMapping(name="Pressure3", formula=[0, 0.00097656, 0.0], type="pressure", unit="bar", precision=3),
    }

    # Layer 3: Instance Override (slave_id 17 specific calibration)
    instance_pin_overrides = {
        "AIn01": {"formula": [0, 0.01220703125, -1.5]},
        "AIn02": {"formula": [0, 0.01220703125, -1.4]},
    }

    result = ConfigManagerExtension.build_final_register_map(
        driver_register_map=driver_register_map,
        pin_mappings=pin_mappings,
        instance_pin_overrides=instance_pin_overrides,
    )

    # AIn01: Has instance override
    assert result["AIn01"]["offset"] == 0  # From driver
    assert result["AIn01"]["format"] == "i16"  # From driver
    assert result["AIn01"]["name"] == "Temp1"  # From pin mapping
    assert result["AIn01"]["type"] == "thermometer"  # From pin mapping
    assert result["AIn01"]["unit"] == "°C"  # From pin mapping
    assert result["AIn01"]["precision"] == 2  # From pin mapping
    assert result["AIn01"]["formula"] == [0, 0.01220703125, -1.5]  # From instance override

    # AIn02: Has instance override
    assert result["AIn02"]["formula"] == [0, 0.01220703125, -1.4]

    # AIn03: No instance override, uses pin mapping
    assert result["AIn03"]["formula"] == [0, 0.00097656, 0.0]
    assert result["AIn03"]["type"] == "pressure"
