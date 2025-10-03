import pytest
from typing import Any


@pytest.fixture
def valid_sd400_config_data() -> dict[str, Any]:
    """Valid SD400 configuration data for testing"""
    return {
        "version": "1.0.0",
        "SD400": {
            "default_controls": [],
            "instances": {
                "3": {
                    "use_default_controls": False,
                    "controls": [
                        # DISCRETE_SETPOINT - No changes needed
                        {
                            "name": "High Temperature Shutdown",
                            "code": "HIGH_TEMP",
                            "priority": 80,
                            "composite": {
                                "any": [
                                    {
                                        "type": "threshold",
                                        "source": "AIn01",
                                        "operator": "gt",
                                        "threshold": 40.0,
                                        "hysteresis": 1.0,
                                        "debounce_sec": 0.5,
                                    }
                                ]
                            },
                            "policy": {"type": "discrete_setpoint"},
                            "action": {
                                "model": "TECO_VFD",
                                "slave_id": "2",
                                "type": "set_frequency",
                                "target": "RW_HZ",
                                "value": 45.0,
                            },
                        },
                        # ABSOLUTE_LINEAR - Fixed to use single sensor
                        {
                            "name": "Environment Temperature Linear Control",
                            "code": "ABS_TEMP01",
                            "priority": 90,
                            "composite": {
                                "any": [
                                    {
                                        "type": "threshold",
                                        "source": "AIn01",  # Single sensor
                                        "operator": "gt",
                                        "threshold": 25.0,  # Trigger when temp > 25°C
                                    }
                                ]
                            },
                            "policy": {
                                "type": "absolute_linear",
                                "condition_type": "threshold",
                                "source": "AIn01",  # ← Fixed: source not sources
                                "base_freq": 40.0,  # Frequency at base_temp
                                "base_temp": 25.0,  # ← Added: required field
                                "gain_hz_per_unit": 1.2,  # 1°C → 1.2Hz
                            },
                            "action": {
                                "model": "TECO_VFD",
                                "slave_id": "2",
                                "type": "set_frequency",
                                "target": "RW_HZ",
                                # value calculated by evaluator
                            },
                        },
                        # INCREMENTAL_LINEAR - Removed max_step_hz
                        {
                            "name": "Supply-Return Temperature Difference Control",
                            "code": "INC_DIFF01",
                            "priority": 95,
                            "composite": {
                                "any": [
                                    {
                                        "type": "difference",
                                        "sources": ["AIn01", "AIn02"],
                                        "operator": "gt",
                                        "threshold": 4.0,
                                    }
                                ]
                            },
                            "policy": {
                                "type": "incremental_linear",
                                "condition_type": "difference",
                                "sources": ["AIn01", "AIn02"],
                                "gain_hz_per_unit": 1.5,  # ← Changed from 1.0 to 1.5
                                # ← Removed: max_step_hz, abs
                            },
                            "action": {
                                "model": "TECO_VFD",
                                "slave_id": "2",
                                "type": "adjust_frequency",
                                "target": "RW_HZ",
                                # value calculated by evaluator
                            },
                        },
                    ],
                }
            },
        },
    }


@pytest.fixture
def minimal_sd400_config_data() -> dict[str, Any]:
    """Minimal valid SD400 configuration"""
    return {"SD400": {"default_controls": [], "instances": {"1": {"use_default_controls": False, "controls": []}}}}


@pytest.fixture
def invalid_version_config_data() -> dict[str, Any]:
    """Configuration with invalid version format"""
    return {"version": "v1.0.0", "SD400": {"default_controls": [], "instances": {}}}  # Invalid format


@pytest.fixture
def config_with_source_kind_legacy() -> dict[str, Any]:
    """Configuration using legacy 'source_kind' instead of 'condition_type'"""
    return {
        "version": "1.0.0",
        "SD400": {
            "default_controls": [],
            "instances": {
                "1": {
                    "use_default_controls": False,
                    "controls": [
                        {
                            "name": "Legacy Policy Test",
                            "code": "LEGACY_TEST",
                            "priority": 50,
                            "composite": {
                                "any": [
                                    {
                                        "type": "difference",
                                        "sources": ["AIn01", "AIn02"],
                                        "operator": "gt",
                                        "threshold": 2.0,
                                    }
                                ]
                            },
                            "policy": {
                                "type": "absolute_linear",
                                "source_kind": "difference",  # Legacy field name
                                "sources": ["AIn01", "AIn02"],
                                "base_freq": 30.0,
                                "gain_hz_per_unit": 2.0,
                            },
                            "action": {
                                "model": "TECO_VFD",
                                "slave_id": "1",
                                "type": "set_frequency",
                                "target": "RW_HZ",
                            },
                        }
                    ],
                }
            },
        },
    }


@pytest.fixture
def config_with_invalid_action_type() -> dict[str, Any]:
    """Configuration with unsupported action type"""
    return {
        "version": "1.0.0",
        "SD400": {
            "default_controls": [],
            "instances": {
                "1": {
                    "use_default_controls": False,
                    "controls": [
                        {
                            "name": "Invalid Action Test",
                            "code": "INVALID_ACTION",
                            "priority": 10,
                            "composite": {
                                "any": [{"type": "threshold", "source": "AIn01", "operator": "gt", "threshold": 10.0}]
                            },
                            "policy": {"type": "discrete_setpoint"},
                            "action": {
                                "model": "TECO_VFD",
                                "slave_id": "1",
                                "type": "unknown_action_type",  # Invalid action type
                                "target": "RW_HZ",
                                "value": 20.0,
                            },
                        }
                    ],
                }
            },
        },
    }


@pytest.fixture
def config_with_duplicate_priorities() -> dict[str, Any]:
    """Configuration with duplicate priorities for deduplication testing"""
    return {
        "version": "1.0.0",
        "SD400": {
            "default_controls": [
                {
                    "name": "Default Rule",
                    "code": "DEFAULT_RULE",
                    "priority": 80,
                    "composite": {
                        "any": [{"type": "threshold", "source": "AIn01", "operator": "gt", "threshold": 50.0}]
                    },
                    "policy": {"type": "discrete_setpoint"},
                    "action": {
                        "model": "TECO_VFD",
                        "slave_id": "2",
                        "type": "set_frequency",
                        "target": "RW_HZ",
                        "value": 30.0,
                    },
                }
            ],
            "instances": {
                "2": {
                    "use_default_controls": True,
                    "controls": [
                        {
                            "name": "Override Rule",
                            "code": "OVERRIDE_RULE",
                            "priority": 80,  # Same priority as default
                            "composite": {
                                "any": [{"type": "threshold", "source": "AIn01", "operator": "gt", "threshold": 60.0}]
                            },
                            "policy": {"type": "discrete_setpoint"},
                            "action": {
                                "model": "TECO_VFD",
                                "slave_id": "2",
                                "type": "set_frequency",
                                "target": "RW_HZ",
                                "value": 50.0,
                            },
                        }
                    ],
                }
            },
        },
    }


@pytest.fixture
def expected_control_count_for_valid_config() -> int:
    """Expected number of controls in valid_sd400_config_data"""
    return 3


@pytest.fixture
def expected_version() -> str:
    """Expected version string for valid configurations"""
    return "1.0.0"


# Additional fixtures for error handling and validation tests
@pytest.fixture
def config_with_invalid_composite() -> dict[str, Any]:
    """Configuration with invalid composite node (empty any array)"""
    return {
        "version": "1.0.0",
        "SD400": {
            "default_controls": [],
            "instances": {
                "1": {
                    "use_default_controls": False,
                    "controls": [
                        {
                            "name": "Invalid Composite",
                            "code": "INVALID",
                            "priority": 10,
                            "composite": {"any": []},  # Empty any - should be invalid
                            "policy": {"type": "discrete_setpoint"},
                            "action": {
                                "model": "TECO_VFD",
                                "slave_id": "1",
                                "type": "set_frequency",
                                "target": "RW_HZ",
                                "value": 10.0,
                            },
                        }
                    ],
                }
            },
        },
    }


@pytest.fixture
def config_with_missing_action() -> dict[str, Any]:
    """Configuration with control that has action but missing action.type"""
    return {
        "version": "1.0.0",
        "SD400": {
            "default_controls": [],
            "instances": {
                "1": {
                    "use_default_controls": False,
                    "controls": [
                        {
                            "name": "Missing Action Type",
                            "code": "MISSING_ACTION_TYPE",
                            "priority": 10,
                            "composite": {
                                "any": [{"type": "threshold", "source": "AIn01", "operator": "gt", "threshold": 10.0}]
                            },
                            "policy": {"type": "discrete_setpoint"},
                            "action": {
                                "model": "TECO_VFD",
                                "slave_id": "1",
                                "target": "RW_HZ",
                                "value": 10.0,
                                # Missing 'type' field - will be None after parsing
                            },
                        }
                    ],
                }
            },
        },
    }


@pytest.fixture
def config_with_string_frequency_value() -> dict[str, Any]:
    """Configuration with SET_FREQUENCY action having string value"""
    return {
        "version": "1.0.0",
        "SD400": {
            "default_controls": [],
            "instances": {
                "1": {
                    "use_default_controls": False,
                    "controls": [
                        {
                            "name": "Set Frequency Test",
                            "code": "SET_FREQ_TEST",
                            "priority": 10,
                            "composite": {
                                "any": [{"type": "threshold", "source": "AIn01", "operator": "gt", "threshold": 10.0}]
                            },
                            "policy": {"type": "discrete_setpoint"},
                            "action": {
                                "model": "TECO_VFD",
                                "slave_id": "1",
                                "type": "set_frequency",
                                "target": "RW_HZ",
                                "value": "45.5",  # String value
                            },
                        }
                    ],
                }
            },
        },
    }


@pytest.fixture
def valid_sd400_config_data() -> dict[str, Any]:
    """Valid SD400 configuration data for testing"""
    return {
        "version": "1.0.0",
        "SD400": {
            "default_controls": [],
            "instances": {
                "3": {
                    "use_default_controls": False,
                    "controls": [
                        # DISCRETE_SETPOINT - No changes needed
                        {
                            "name": "High Temperature Shutdown",
                            "code": "HIGH_TEMP",
                            "priority": 80,
                            "composite": {
                                "any": [
                                    {
                                        "type": "threshold",
                                        "source": "AIn01",
                                        "operator": "gt",
                                        "threshold": 40.0,
                                        "hysteresis": 1.0,
                                        "debounce_sec": 0.5,
                                    }
                                ]
                            },
                            "policy": {"type": "discrete_setpoint"},
                            "action": {
                                "model": "TECO_VFD",
                                "slave_id": "2",
                                "type": "set_frequency",
                                "target": "RW_HZ",
                                "value": 45.0,
                            },
                        },
                        # ABSOLUTE_LINEAR - Fixed to use single sensor
                        {
                            "name": "Environment Temperature Linear Control",
                            "code": "LIN_ABS01",
                            "priority": 90,
                            "composite": {
                                "any": [
                                    {
                                        "type": "threshold",
                                        "source": "AIn01",  # Single sensor
                                        "operator": "gt",
                                        "threshold": 25.0,  # Trigger when temp > 25°C
                                    }
                                ]
                            },
                            "policy": {
                                "type": "absolute_linear",
                                "condition_type": "threshold",
                                "source": "AIn01",  # ← Fixed: source not sources
                                "base_freq": 40.0,  # Frequency at base_temp
                                "base_temp": 25.0,  # ← Added: required field
                                "gain_hz_per_unit": 1.2,  # 1°C → 1.2Hz
                            },
                            "action": {
                                "model": "TECO_VFD",
                                "slave_id": "2",
                                "type": "set_frequency",
                                "target": "RW_HZ",
                                # value calculated by evaluator
                            },
                        },
                        # INCREMENTAL_LINEAR - Removed max_step_hz
                        {
                            "name": "Supply-Return Temperature Difference Control",
                            "code": "LIN_INC01",  # ← 恢復原來的 code
                            "priority": 95,  # ← 恢復原來的 95
                            "composite": {
                                "any": [
                                    {
                                        "type": "difference",
                                        "sources": ["AIn01", "AIn02"],
                                        "operator": "gt",
                                        "threshold": 4.0,
                                    }
                                ]
                            },
                            "policy": {
                                "type": "incremental_linear",
                                "condition_type": "difference",
                                "sources": ["AIn01", "AIn02"],
                                "gain_hz_per_unit": 1.5,  # ← Changed from 1.0 to 1.5
                                # ← Removed: max_step_hz, abs
                            },
                            "action": {
                                "model": "TECO_VFD",
                                "slave_id": "2",
                                "type": "adjust_frequency",
                                "target": "RW_HZ",
                                # value calculated by evaluator
                            },
                        },
                    ],
                }
            },
        },
    }


# Advanced validation test fixtures
@pytest.fixture
def config_with_circular_reference() -> dict[str, Any]:
    """Configuration that would create circular reference (for testing detection)"""
    # Note: This is conceptually what we want to test, but we can't actually create
    # a circular reference in static YAML. The detection logic will be tested
    # through unit tests that manually construct circular structures.
    return {
        "version": "1.0.0",
        "SD400": {
            "default_controls": [],
            "instances": {
                "1": {
                    "use_default_controls": False,
                    "controls": [
                        {
                            "name": "Deep Nesting Test",
                            "code": "DEEP_NEST",
                            "priority": 10,
                            "composite": {
                                "all": [
                                    {
                                        "any": [
                                            {
                                                "all": [
                                                    {
                                                        "any": [
                                                            {
                                                                "type": "threshold",
                                                                "source": "AIn01",
                                                                "operator": "gt",
                                                                "threshold": 10.0,
                                                            }
                                                        ]
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            "policy": {"type": "discrete_setpoint"},
                            "action": {
                                "model": "TECO_VFD",
                                "slave_id": "1",
                                "type": "set_frequency",
                                "target": "RW_HZ",
                                "value": 10.0,
                            },
                        }
                    ],
                }
            },
        },
    }


@pytest.fixture
def config_with_invalid_operator_combinations() -> dict[str, Any]:
    """Configuration with invalid operator-threshold combinations"""
    return {
        "version": "1.0.0",
        "SD400": {
            "default_controls": [],
            "instances": {
                "1": {
                    "use_default_controls": False,
                    "controls": [
                        {
                            "name": "Invalid BETWEEN Test",
                            "code": "INVALID_BETWEEN",
                            "priority": 10,
                            "composite": {
                                "any": [
                                    {
                                        "type": "threshold",
                                        "source": "AIn01",
                                        "operator": "between",
                                        "min": 15.0,  # min > max (invalid)
                                        "max": 10.0,
                                        "threshold": 12.0,  # shouldn't be used with BETWEEN
                                    }
                                ]
                            },
                            "policy": {"type": "discrete_setpoint"},
                            "action": {
                                "model": "TECO_VFD",
                                "slave_id": "1",
                                "type": "set_frequency",
                                "target": "RW_HZ",
                                "value": 20.0,
                            },
                        }
                    ],
                }
            },
        },
    }


@pytest.fixture
def config_with_duplicate_difference_sources() -> dict[str, Any]:
    """Configuration with difference condition having duplicate sources"""
    return {
        "version": "1.0.0",
        "SD400": {
            "default_controls": [],
            "instances": {
                "1": {
                    "use_default_controls": False,
                    "controls": [
                        {
                            "name": "Duplicate Sources Test",
                            "code": "DUP_SOURCES",
                            "priority": 10,
                            "composite": {
                                "any": [
                                    {
                                        "type": "difference",
                                        "sources": ["AIn01", "AIn01"],  # Same source twice
                                        "operator": "gt",
                                        "threshold": 5.0,
                                    }
                                ]
                            },
                            "policy": {
                                "type": "incremental_linear",  # ← Changed to incremental_linear
                                "condition_type": "difference",
                                "sources": ["AIn01", "AIn01"],
                                "gain_hz_per_unit": 1.5,
                                # ← Removed: base_freq
                            },
                            "action": {
                                "model": "TECO_VFD",
                                "slave_id": "1",
                                "type": "adjust_frequency",  # ← Changed to adjust_frequency
                                "target": "RW_HZ",
                            },
                        }
                    ],
                }
            },
        },
    }


@pytest.fixture
def config_with_invalid_composite() -> dict[str, Any]:
    """Configuration with invalid composite node (empty any array)"""
    return {
        "version": "1.0.0",
        "SD400": {
            "default_controls": [],
            "instances": {
                "1": {
                    "use_default_controls": False,
                    "controls": [
                        {
                            "name": "Invalid Composite",
                            "code": "INVALID",
                            "priority": 10,
                            "composite": {"any": []},  # Empty any - should be invalid
                            "policy": {"type": "discrete_setpoint"},
                            "action": {
                                "model": "TECO_VFD",
                                "slave_id": "1",
                                "type": "set_frequency",
                                "target": "RW_HZ",
                                "value": 10.0,
                            },
                        }
                    ],
                }
            },
        },
    }


@pytest.fixture
def config_with_missing_action() -> dict[str, Any]:
    """Configuration with control that has no action field"""
    return {
        "version": "1.0.0",
        "SD400": {
            "default_controls": [],
            "instances": {
                "1": {
                    "use_default_controls": False,
                    "controls": [
                        {
                            "name": "No Action",
                            "code": "NO_ACTION",
                            "priority": 10,
                            "composite": {
                                "any": [{"type": "threshold", "source": "AIn01", "operator": "gt", "threshold": 10.0}]
                            },
                            "policy": {"type": "discrete_setpoint"},
                            # Missing action field
                        }
                    ],
                }
            },
        },
    }


@pytest.fixture
def config_with_invalid_policy() -> dict[str, Any]:
    """Configuration with invalid policy (missing required fields)"""
    return {
        "version": "1.0.0",
        "SD400": {
            "default_controls": [],
            "instances": {
                "1": {
                    "use_default_controls": False,
                    "controls": [
                        {
                            "name": "Invalid Policy",
                            "code": "INVALID_POLICY",
                            "priority": 10,
                            "composite": {
                                "any": [{"type": "threshold", "source": "AIn01", "operator": "gt", "threshold": 10.0}]
                            },
                            "policy": {
                                "type": "absolute_linear",
                                "condition_type": "threshold",
                                "source": "AIn01",
                                # Missing required base_freq, base_temp and gain_hz_per_unit
                            },
                            "action": {
                                "model": "TECO_VFD",
                                "slave_id": "1",
                                "type": "set_frequency",
                                "target": "RW_HZ",
                                "value": 10.0,
                            },
                        }
                    ],
                }
            },
        },
    }


@pytest.fixture
def config_with_string_frequency_value() -> dict[str, Any]:
    """Configuration with SET_FREQUENCY action having string value"""
    return {
        "version": "1.0.0",
        "SD400": {
            "default_controls": [],
            "instances": {
                "1": {
                    "use_default_controls": False,
                    "controls": [
                        {
                            "name": "Set Frequency Test",
                            "code": "SET_FREQ_TEST",
                            "priority": 10,
                            "composite": {
                                "any": [{"type": "threshold", "source": "AIn01", "operator": "gt", "threshold": 10.0}]
                            },
                            "policy": {"type": "discrete_setpoint"},
                            "action": {
                                "model": "TECO_VFD",
                                "slave_id": "1",
                                "type": "set_frequency",
                                "target": "RW_HZ",
                                "value": "45.5",  # String value
                            },
                        }
                    ],
                }
            },
        },
    }


@pytest.fixture
def config_with_string_adjust_frequency_value() -> dict[str, Any]:
    """Configuration with ADJUST_FREQUENCY action having string value"""
    return {
        "version": "1.0.0",
        "SD400": {
            "default_controls": [],
            "instances": {
                "1": {
                    "use_default_controls": False,
                    "controls": [
                        {
                            "name": "Adjust Frequency Test",
                            "code": "ADJUST_FREQ_TEST",
                            "priority": 10,
                            "composite": {
                                "any": [{"type": "threshold", "source": "AIn01", "operator": "gt", "threshold": 10.0}]
                            },
                            "policy": {
                                "type": "incremental_linear",
                                "condition_type": "threshold",
                                "source": "AIn01",
                                "gain_hz_per_unit": 1.0,
                                # ← Removed: max_step_hz
                            },
                            "action": {
                                "model": "TECO_VFD",
                                "slave_id": "1",
                                "type": "adjust_frequency",
                                "target": "RW_HZ",
                                "value": "-2.5",  # String value (negative adjustment)
                            },
                        }
                    ],
                }
            },
        },
    }
