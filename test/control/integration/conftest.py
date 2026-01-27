import pytest

from core.schema.constraint_schema import ConstraintConfigSchema
from core.schema.control_config_schema import ControlConfig

# ---------------------------------------------------------------------
# Test-only migrated control config (DO NOT read site YAML)
# Keep this minimal but representative:
# - Emergency: 0
# - Recovery: 20-23
# - Device control: 80-81
# - Normal control: 90-91
# ---------------------------------------------------------------------
MIGRATED_CONTROL_CONFIG_DICT: dict = {
    "version": "1.0.0",
    "ADAM-4117": {
        "instances": {
            "12": {
                "use_default_controls": False,
                "controls": [
                    {
                        "name": "Loop1-R1 - Fermenter Emergency",
                        "code": "LOOP1_R1_EMERGENCY",
                        "priority": 0,
                        "composite": {
                            "any": [
                                {
                                    "type": "average",
                                    "sources": [
                                        {"device": "ADAM-4117", "slave_id": "12", "pins": ["AIn01"]},
                                        {"device": "ADAM-4117", "slave_id": "12", "pins": ["AIn02"]},
                                        {"device": "ADAM-4117", "slave_id": "12", "pins": ["AIn03"]},
                                    ],
                                    "operator": "gt",
                                    "threshold": 39.0,
                                    "hysteresis": 0.5,
                                    "debounce_sec": 0.0,
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
                                "value": 60,
                                "emergency_override": True,
                            },
                        ],
                    },
                    {
                        "name": "Loop1-R1 - Fermenter Speed Up",
                        "code": "LOOP1_R1_SPEED_UP",
                        "priority": 90,
                        "composite": {
                            "any": [
                                {
                                    "type": "average",
                                    "sources": [
                                        {"device": "ADAM-4117", "slave_id": "12", "pins": ["AIn01"]},
                                        {"device": "ADAM-4117", "slave_id": "12", "pins": ["AIn02"]},
                                        {"device": "ADAM-4117", "slave_id": "12", "pins": ["AIn03"]},
                                    ],
                                    "operator": "gt",
                                    "threshold": 19.0,
                                    "hysteresis": 0.5,
                                    "debounce_sec": 3.0,
                                }
                            ]
                        },
                        "policy": {"type": "discrete_setpoint"},
                        "actions": [
                            {
                                "model": "TECO_VFD",
                                "slave_id": "1",
                                "type": "adjust_frequency",
                                "target": "RW_HZ",
                                "value": 2.0,
                            },
                        ],
                    },
                    {
                        "name": "Loop1-R1 - Fermenter Slow Down",
                        "code": "LOOP1_R1_SLOW_DOWN",
                        "priority": 91,
                        "composite": {
                            "any": [
                                {
                                    "type": "average",
                                    "sources": [
                                        {"device": "ADAM-4117", "slave_id": "12", "pins": ["AIn01"]},
                                        {"device": "ADAM-4117", "slave_id": "12", "pins": ["AIn02"]},
                                        {"device": "ADAM-4117", "slave_id": "12", "pins": ["AIn03"]},
                                    ],
                                    "operator": "lt",
                                    "threshold": 19.0,
                                    "hysteresis": 0.5,
                                    "debounce_sec": 3.0,
                                }
                            ]
                        },
                        "policy": {"type": "discrete_setpoint"},
                        "actions": [
                            {
                                "model": "TECO_VFD",
                                "slave_id": "1",
                                "type": "adjust_frequency",
                                "target": "RW_HZ",
                                "value": -2.0,
                            },
                        ],
                    },
                ],
            },
        }
    },
    "TECO_VFD": {
        "instances": {
            "1": {
                "use_default_controls": False,
                "controls": [
                    {
                        "name": "VFD Error Reset (S1)",
                        "code": "VFD_ERROR_RESET_S1",
                        "priority": 20,
                        "blocking": True,
                        "composite": {
                            "any": [
                                {
                                    "type": "threshold",
                                    "sources": [{"device": "TECO_VFD", "slave_id": "1", "pins": ["ALERT"]}],
                                    "operator": "gt",
                                    "threshold": 0.0,
                                    "hysteresis": 0.0,
                                    "debounce_sec": 0.0,
                                }
                            ]
                        },
                        "policy": {"type": "discrete_setpoint"},
                        "actions": [
                            {
                                "model": "TECO_VFD",
                                "slave_id": "1",
                                "type": "reset",
                                "target": "RW_RESET",
                                "value": 9,
                            }
                        ],
                    },
                    {
                        "name": "VFD Error Recovery Turn On (S1)",
                        "code": "VFD_ERROR_RECOVERY_ON_S1",
                        "priority": 21,
                        "composite": {
                            "all": [
                                {
                                    "type": "threshold",
                                    "sources": [{"device": "TECO_VFD", "slave_id": "1", "pins": ["ALERT"]}],
                                    "operator": "eq",
                                    "threshold": 0.0,
                                    "debounce_sec": 0.0,
                                },
                                {
                                    "type": "threshold",
                                    "sources": [{"device": "TECO_VFD", "slave_id": "1", "pins": ["ERROR"]}],
                                    "operator": "eq",
                                    "threshold": 0.0,
                                    "debounce_sec": 0.0,
                                },
                                {
                                    "type": "threshold",
                                    "sources": [{"device": "TECO_VFD", "slave_id": "1", "pins": ["RW_ON_OFF"]}],
                                    "operator": "eq",
                                    "threshold": 0.0,
                                    "debounce_sec": 0.0,
                                },
                            ]
                        },
                        "policy": {"type": "discrete_setpoint"},
                        "actions": [
                            {
                                "model": "TECO_VFD",
                                "slave_id": "1",
                                "type": "turn_on",
                                "target": "RW_ON_OFF",
                            }
                        ],
                    },
                    {
                        "name": "Fan Shutdown Example",
                        "code": "FAN_SHUTDOWN_EXAMPLE",
                        "priority": 80,
                        "composite": {
                            "any": [
                                {
                                    "type": "threshold",
                                    "sources": [{"device": "TECO_VFD", "slave_id": "1", "pins": ["AIn01"]}],
                                    "operator": "lt",
                                    "threshold": 10.0,
                                    "hysteresis": 0.5,
                                    "debounce_sec": 3.0,
                                }
                            ]
                        },
                        "policy": {"type": "discrete_setpoint"},
                        "actions": [
                            {
                                "model": "TECO_VFD",
                                "slave_id": "1",
                                "type": "turn_off",
                                "target": "RW_ON_OFF",
                            }
                        ],
                    },
                    {
                        "name": "Fan Turn On Example",
                        "code": "FAN_TURN_ON_EXAMPLE",
                        "priority": 81,
                        "composite": {
                            "any": [
                                {
                                    "type": "threshold",
                                    "sources": [{"device": "TECO_VFD", "slave_id": "1", "pins": ["AIn01"]}],
                                    "operator": "gt",
                                    "threshold": 12.0,
                                    "hysteresis": 0.5,
                                    "debounce_sec": 3.0,
                                }
                            ]
                        },
                        "policy": {"type": "discrete_setpoint"},
                        "actions": [
                            {
                                "model": "TECO_VFD",
                                "slave_id": "1",
                                "type": "turn_on",
                                "target": "RW_ON_OFF",
                            }
                        ],
                    },
                ],
            },
        }
    },
}

# If your tests need a constraints object but you don't want to read site files,
# provide a minimal valid one as well.
MIN_CONSTRAINTS_DICT: dict = {
    "version": "1.0.0",
    "devices": {},
}


@pytest.fixture(scope="session")
def migrated_control_config_dict() -> dict:
    return MIGRATED_CONTROL_CONFIG_DICT


@pytest.fixture(scope="session")
def control_config(migrated_control_config_dict: dict) -> ControlConfig:
    return ControlConfig(**migrated_control_config_dict)


@pytest.fixture(scope="session")
def constraint_config() -> ConstraintConfigSchema:
    return ConstraintConfigSchema(**MIN_CONSTRAINTS_DICT)
