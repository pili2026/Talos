from typing import Any

import pytest


@pytest.fixture
def valid_sd400_config_data() -> dict[str, Any]:
    """Valid SD400 configuration data for testing (v2.0 format)"""
    return {
        "version": "1.0.0",
        "SD400": {
            "default_controls": [],
            "instances": {
                "3": {
                    "use_default_controls": False,
                    "controls": [
                        # DISCRETE_SETPOINT
                        {
                            "name": "High Temperature Shutdown",
                            "code": "HIGH_TEMP",
                            "priority": 80,
                            "composite": {
                                "any": [
                                    {
                                        "sources_id": "SD400.3:AIn01",
                                        "type": "threshold",
                                        "sources": [{"device": "SD400", "slave_id": "3", "pins": ["AIn01"]}],
                                        "operator": "gt",
                                        "threshold": 40.0,
                                        "hysteresis": 1.0,
                                        "debounce_sec": 0.5,
                                    }
                                ]
                            },
                            "policy": {"type": "discrete_setpoint"},
                            "actions": [
                                {
                                    "model": "TECO_VFD",
                                    "slave_id": "2",
                                    "type": "set_frequency",
                                    "target": "RW_HZ",
                                    "value": 45.0,
                                }
                            ],
                        },
                        # ABSOLUTE_LINEAR
                        {
                            "name": "Environment Temperature Linear Control",
                            "code": "LIN_ABS01",
                            "priority": 90,
                            "composite": {
                                "any": [
                                    {
                                        "sources_id": "SD400.3:AIn01",
                                        "type": "threshold",
                                        "sources": [{"device": "SD400", "slave_id": "3", "pins": ["AIn01"]}],
                                        "operator": "gt",
                                        "threshold": 25.0,
                                    }
                                ]
                            },
                            "policy": {
                                "type": "absolute_linear",
                                "input_source": "SD400.3:AIn01",
                                "base_freq": 40.0,
                                "base_temp": 25.0,
                                "gain_hz_per_unit": 1.2,
                            },
                            "actions": [
                                {
                                    "model": "TECO_VFD",
                                    "slave_id": "2",
                                    "type": "set_frequency",
                                    "target": "RW_HZ",
                                    "value": 0.0,  # executor/engine should overwrite based on computed policy output
                                }
                            ],
                        },
                        # INCREMENTAL_LINEAR
                        {
                            "name": "Supply-Return Temperature Difference Control",
                            "code": "LIN_INC01",
                            "priority": 95,
                            "composite": {
                                "any": [
                                    {
                                        "sources_id": "SD400.3:AIn01-AIn02",
                                        "type": "difference",
                                        "sources": [
                                            {"device": "SD400", "slave_id": "3", "pins": ["AIn01"]},
                                            {"device": "SD400", "slave_id": "3", "pins": ["AIn02"]},
                                        ],
                                        "operator": "gt",
                                        "threshold": 4.0,
                                    }
                                ]
                            },
                            "policy": {
                                "type": "incremental_linear",
                                "input_source": "SD400.3:AIn01-AIn02",
                                "gain_hz_per_unit": 1.5,
                            },
                            "actions": [
                                {
                                    "model": "TECO_VFD",
                                    "slave_id": "2",
                                    "type": "adjust_frequency",
                                    "target": "RW_HZ",
                                    "value": 1.5,  # usually "base step"; policy may scale this
                                }
                            ],
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
    return {"version": "v1.0.0", "SD400": {"default_controls": [], "instances": {}}}


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
                                        "sources": [
                                            {"device": "SD400", "slave_id": "1", "pins": ["AIn01"]},
                                            {"device": "SD400", "slave_id": "1", "pins": ["AIn02"]},
                                        ],
                                        "operator": "gt",
                                        "threshold": 2.0,
                                    }
                                ]
                            },
                            "policy": {
                                "type": "absolute_linear",
                                "source_kind": "difference",  # Legacy field
                                "sources": ["AIn01", "AIn02"],
                                "base_freq": 30.0,
                                "gain_hz_per_unit": 2.0,
                            },
                            "actions": [
                                {
                                    "model": "TECO_VFD",
                                    "slave_id": "1",
                                    "type": "set_frequency",
                                    "target": "RW_HZ",
                                }
                            ],
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
                                "any": [
                                    {
                                        "type": "threshold",
                                        "sources": [{"device": "SD400", "slave_id": "1", "pins": ["AIn01"]}],
                                        "operator": "gt",
                                        "threshold": 10.0,
                                    }
                                ]
                            },
                            "policy": {"type": "discrete_setpoint"},
                            "actions": [
                                {
                                    "model": "TECO_VFD",
                                    "slave_id": "1",
                                    "type": "unknown_action_type",  # Invalid
                                    "target": "RW_HZ",
                                    "value": 20.0,
                                }
                            ],
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
                        "any": [
                            {
                                "type": "threshold",
                                "sources": [{"device": "SD400", "slave_id": "2", "pins": ["AIn01"]}],
                                "operator": "gt",
                                "threshold": 50.0,
                            }
                        ]
                    },
                    "policy": {"type": "discrete_setpoint"},
                    "actions": [
                        {
                            "model": "TECO_VFD",
                            "slave_id": "2",
                            "type": "set_frequency",
                            "target": "RW_HZ",
                            "value": 30.0,
                        }
                    ],
                }
            ],
            "instances": {
                "2": {
                    "use_default_controls": True,
                    "controls": [
                        {
                            "name": "Override Rule",
                            "code": "OVERRIDE_RULE",
                            "priority": 80,
                            "composite": {
                                "any": [
                                    {
                                        "type": "threshold",
                                        "sources": [{"device": "SD400", "slave_id": "2", "pins": ["AIn01"]}],
                                        "operator": "gt",
                                        "threshold": 60.0,
                                    }
                                ]
                            },
                            "policy": {"type": "discrete_setpoint"},
                            "actions": [
                                {
                                    "model": "TECO_VFD",
                                    "slave_id": "2",
                                    "type": "set_frequency",
                                    "target": "RW_HZ",
                                    "value": 50.0,
                                }
                            ],
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
                            "composite": {"any": []},  # Empty - invalid
                            "policy": {"type": "discrete_setpoint"},
                            "actions": [
                                {
                                    "model": "TECO_VFD",
                                    "slave_id": "1",
                                    "type": "set_frequency",
                                    "target": "RW_HZ",
                                    "value": 10.0,
                                }
                            ],
                        }
                    ],
                }
            },
        },
    }


@pytest.fixture
def config_with_missing_action() -> dict[str, Any]:
    """Configuration with control that has no actions field"""
    return {
        "version": "1.0.0",
        "SD400": {
            "default_controls": [],
            "instances": {
                "1": {
                    "use_default_controls": False,
                    "controls": [
                        {
                            "name": "No Actions",
                            "code": "NO_ACTIONS",
                            "priority": 10,
                            "composite": {
                                "any": [
                                    {
                                        "type": "threshold",
                                        "sources": [{"device": "SD400", "slave_id": "1", "pins": ["AIn01"]}],
                                        "operator": "gt",
                                        "threshold": 10.0,
                                    }
                                ]
                            },
                            "policy": {"type": "discrete_setpoint"},
                            # Missing actions field entirely
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
                                "any": [
                                    {
                                        "type": "threshold",
                                        "sources": [{"device": "SD400", "slave_id": "1", "pins": ["AIn01"]}],
                                        "operator": "gt",
                                        "threshold": 10.0,
                                    }
                                ]
                            },
                            "policy": {"type": "discrete_setpoint"},
                            "actions": [
                                {
                                    "model": "TECO_VFD",
                                    "slave_id": "1",
                                    "type": "set_frequency",
                                    "target": "RW_HZ",
                                    "value": "45.5",  # String value
                                }
                            ],
                        }
                    ],
                }
            },
        },
    }


@pytest.fixture
def config_with_string_adjust_frequency_value() -> dict[str, Any]:
    """
    Configuration with string value for ADJUST_FREQUENCY action.

    Tests that action.value is properly coerced from string to float.
    """
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
                            "composite": {
                                "any": [
                                    {
                                        "sources_id": "cond_0",  # ✅ v2.0: condition ID
                                        "type": "threshold",
                                        "sources": [  # ✅ v2.0: Source objects
                                            {"device": "SD400", "slave_id": "1", "pins": ["AIn01"]}
                                        ],
                                        "operator": "gt",
                                        "threshold": 10.0,
                                    }
                                ]
                            },
                            "policy": {
                                "type": "incremental_linear",
                                "input_source": "cond_0",
                                "gain_hz_per_unit": 1.5,
                            },
                            "actions": [
                                {
                                    "model": "TECO_VFD",
                                    "slave_id": "1",
                                    "type": "adjust_frequency",
                                    "target": "RW_HZ",
                                    "value": "1.5",
                                }
                            ],
                        }
                    ],
                }
            },
        },
    }


@pytest.fixture
def config_with_circular_reference() -> dict[str, Any]:
    """Configuration with deep nesting for testing"""
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
                                                                "sources": [
                                                                    {
                                                                        "device": "SD400",
                                                                        "slave_id": "1",
                                                                        "pins": ["AIn01"],
                                                                    }
                                                                ],
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
                            "actions": [
                                {
                                    "model": "TECO_VFD",
                                    "slave_id": "1",
                                    "type": "set_frequency",
                                    "target": "RW_HZ",
                                    "value": 10.0,
                                }
                            ],
                        }
                    ],
                }
            },
        },
    }


@pytest.fixture
def config_with_invalid_operator_combinations() -> dict[str, Any]:
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
                                        "sources": [{"device": "SD400", "slave_id": "1", "pins": ["AIn01"]}],
                                        "operator": "between",
                                        "min": 15.0,
                                        "max": 10.0,  # invalid: min >= max
                                        # optional: deliberately also invalid
                                        # "threshold": 12.0,
                                    }
                                ]
                            },
                            "policy": {"type": "discrete_setpoint"},
                            "actions": [
                                {
                                    "model": "TECO_VFD",
                                    "slave_id": "1",
                                    "type": "set_frequency",
                                    "target": "RW_HZ",
                                    "value": 20.0,
                                }
                            ],
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
                                        "sources": [
                                            {"device": "SD400", "slave_id": "1", "pins": ["AIn01"]},
                                            {"device": "SD400", "slave_id": "1", "pins": ["AIn01"]},
                                        ],
                                        "operator": "gt",
                                        "threshold": 5.0,
                                    }
                                ]
                            },
                            "policy": {
                                "type": "incremental_linear",
                                "condition_type": "difference",
                                "sources": ["AIn01", "AIn01"],
                                "gain_hz_per_unit": 1.5,
                            },
                            "actions": [
                                {
                                    "model": "TECO_VFD",
                                    "slave_id": "1",
                                    "type": "adjust_frequency",
                                    "target": "RW_HZ",
                                }
                            ],
                        }
                    ],
                }
            },
        },
    }


@pytest.fixture
def config_with_invalid_policy() -> dict[str, Any]:
    """
    Configuration with invalid policy (missing required fields for absolute_linear).
    """
    return {
        "version": "1.0.0",
        "SD400": {
            "default_controls": [],
            "instances": {
                "1": {
                    "use_default_controls": False,
                    "controls": [
                        {
                            "name": "Invalid Policy - Missing Required Fields",
                            "code": "INVALID_POLICY",
                            "priority": 10,
                            "composite": {
                                "any": [
                                    {
                                        "sources_id": "cond_0",
                                        "type": "threshold",
                                        "sources": [{"device": "SD400", "slave_id": "1", "pins": ["AIn01"]}],
                                        "operator": "gt",
                                        "threshold": 10.0,
                                    }
                                ]
                            },
                            "policy": {
                                "type": "absolute_linear",
                                "input_source": "cond_0",
                                # ❌ Missing: base_freq, base_temp, gain_hz_per_unit
                            },
                            "actions": [
                                {
                                    "model": "TECO_VFD",
                                    "slave_id": "1",
                                    "type": "set_frequency",
                                    "target": "RW_HZ",
                                    "value": 10.0,
                                }
                            ],
                        }
                    ],
                }
            },
        },
    }


@pytest.fixture
def config_with_missing_input_source() -> dict[str, Any]:
    """Configuration with policy missing input_source"""
    return {
        "version": "1.0.0",
        "SD400": {
            "instances": {
                "1": {
                    "controls": [
                        {
                            "name": "Missing Input Source",
                            "code": "NO_INPUT",
                            "composite": {
                                "any": [
                                    {
                                        "sources_id": "cond_0",
                                        "type": "threshold",
                                        "sources": [{"device": "SD400", "slave_id": "1", "pins": ["AIn01"]}],
                                        "operator": "gt",
                                        "threshold": 25.0,
                                    }
                                ]
                            },
                            "policy": {
                                "type": "absolute_linear",
                                # Missing input_source
                                "base_freq": 40.0,
                                "base_temp": 25.0,
                                "gain_hz_per_unit": 1.2,
                            },
                            "actions": [
                                {
                                    "model": "TECO_VFD",
                                    "slave_id": "1",
                                    "type": "set_frequency",
                                    "target": "RW_HZ",
                                    "value": 0.0,
                                }
                            ],
                        }
                    ]
                }
            }
        },
    }


@pytest.fixture
def config_with_wrong_condition_reference() -> dict[str, Any]:
    """Configuration where policy references non-existent condition ID"""
    return {
        "version": "1.0.0",
        "SD400": {
            "instances": {
                "1": {
                    "controls": [
                        {
                            "name": "Wrong Reference",
                            "code": "BAD_REF",
                            "composite": {
                                "any": [
                                    {
                                        "sources_id": "cond_0",  # ← Actual condition ID
                                        "type": "threshold",
                                        "sources": [{"device": "SD400", "slave_id": "1", "pins": ["AIn01"]}],
                                        "operator": "gt",
                                        "threshold": 25.0,
                                    }
                                ]
                            },
                            "policy": {
                                "type": "absolute_linear",
                                "input_source": "wrong_id",  # ← References non-existent ID
                                "base_freq": 40.0,
                                "base_temp": 25.0,
                                "gain_hz_per_unit": 1.2,
                            },
                            "actions": [
                                {
                                    "model": "TECO_VFD",
                                    "slave_id": "1",
                                    "type": "set_frequency",
                                    "target": "RW_HZ",
                                    "value": 0.0,
                                }
                            ],
                        }
                    ]
                }
            }
        },
    }
