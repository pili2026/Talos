import logging
import re

import pytest
from pydantic import ValidationError

from core.schema.control_config_schema import ControlConfig


def _src(device: str, slave_id: str, pin: str) -> dict:
    return {"device": device, "slave_id": slave_id, "pins": [pin]}


class TestPriorityValidation:
    """Test priority validation integrated into ControlConfig"""

    def test_when_emergency_rule_has_priority_zero_then_config_loads_successfully(self):
        config_dict = {
            "version": "1.0.0",
            "root": {  # 統一用 root（避免你 ControlConfig 結構有兩種寫法混用）
                "TECO_VFD": {
                    "default_controls": [],
                    "instances": {
                        "1": {
                            "use_default_controls": False,
                            "controls": [
                                {
                                    "name": "Emergency Protection",
                                    "code": "EMERGENCY",
                                    "priority": 0,
                                    "composite": {
                                        "any": [
                                            {
                                                "type": "threshold",
                                                "sources": [_src("TECO_VFD", "1", "HZ")],
                                                "operator": "lte",
                                                "threshold": 30.0,
                                            }
                                        ]
                                    },
                                    "actions": [
                                        {
                                            "model": "TECO_VFD",
                                            "slave_id": "1",
                                            "type": "set_frequency",
                                            "target": "RW_HZ",
                                            "value": 60.0,
                                            "emergency_override": True,
                                        }
                                    ],
                                }
                            ],
                        }
                    },
                },
            },
        }

        config = ControlConfig(**config_dict)
        assert config.version == "1.0.0"

        rules = config.get_control_list("TECO_VFD", "1")
        assert len(rules) == 1
        assert rules[0].priority == 0

    def test_when_emergency_override_has_high_priority_then_validation_error_is_raised(self):
        config_dict = {
            "version": "1.0.0",
            "root": {
                "TECO_VFD": {
                    "default_controls": [],
                    "instances": {
                        "1": {
                            "use_default_controls": False,
                            "controls": [
                                {
                                    "name": "Bad Emergency",
                                    "code": "BAD_EMERGENCY",
                                    "priority": 50,  # invalid
                                    "composite": {
                                        "any": [
                                            {
                                                "type": "threshold",
                                                "sources": [_src("TECO_VFD", "1", "HZ")],
                                                "operator": "lte",
                                                "threshold": 30.0,
                                            }
                                        ]
                                    },
                                    "actions": [
                                        {
                                            "model": "TECO_VFD",
                                            "slave_id": "1",
                                            "type": "set_frequency",
                                            "emergency_override": True,
                                            "value": 60.0,
                                        }
                                    ],
                                }
                            ],
                        }
                    },
                }
            },
        }

        with pytest.raises(ValidationError) as exc_info:
            ControlConfig(**config_dict)

        error_msg = str(exc_info.value)
        assert "emergency_override=True requires priority < 10" in error_msg
        assert re.search(r"(priority=50|got 50|got priority=50)", error_msg), error_msg

    def test_when_time_override_rule_has_valid_priority_and_time_range_then_config_loads_successfully(self):
        config_dict = {
            "version": "1.0.0",
            "root": {
                "TECO_VFD": {
                    "default_controls": [],
                    "instances": {
                        "3": {
                            "use_default_controls": False,
                            "controls": [
                                {
                                    "name": "Morning Fixed Frequency",
                                    "code": "MORNING_FIXED",
                                    "priority": 10,
                                    "active_time_ranges": [{"start": "09:00", "end": "12:00"}],
                                    "composite": {
                                        "any": [
                                            {
                                                "type": "threshold",
                                                "sources": [_src("TECO_VFD", "3", "RO_TEMPERATURE")],
                                                "operator": "gte",
                                                "threshold": 0.0,
                                            }
                                        ]
                                    },
                                    "actions": [
                                        {
                                            "model": "TECO_VFD",
                                            "slave_id": "3",
                                            "type": "set_frequency",
                                            "value": 30.0,
                                        }
                                    ],
                                }
                            ],
                        }
                    },
                }
            },
        }

        config = ControlConfig(**config_dict)
        rules = config.get_control_list("TECO_VFD", "3")
        assert len(rules) == 1
        assert rules[0].active_time_ranges is not None

    def test_when_time_override_rule_uses_emergency_priority_then_validation_error_is_raised(self):
        config_dict = {
            "version": "1.0.0",
            "root": {
                "TECO_VFD": {
                    "default_controls": [],
                    "instances": {
                        "3": {
                            "use_default_controls": False,
                            "controls": [
                                {
                                    "name": "Bad Time Override",
                                    "code": "BAD_TIME",
                                    "priority": 0,  # invalid for time override
                                    "active_time_ranges": [{"start": "09:00", "end": "12:00"}],
                                    "composite": {
                                        "any": [
                                            {
                                                "type": "threshold",
                                                "sources": [_src("TECO_VFD", "3", "RO_TEMPERATURE")],
                                                "operator": "gte",
                                                "threshold": 0.0,
                                            }
                                        ]
                                    },
                                    "actions": [
                                        {
                                            "model": "TECO_VFD",
                                            "slave_id": "3",
                                            "type": "set_frequency",
                                            "value": 30.0,
                                        }
                                    ],
                                }
                            ],
                        }
                    },
                }
            },
        }

        with pytest.raises(ValidationError) as exc_info:
            ControlConfig(**config_dict)

        error_msg = str(exc_info.value)
        assert "requires priority >= 10" in error_msg

    def test_when_time_override_priority_is_not_recommended_then_warning_is_logged_and_config_still_loads(self, caplog):
        caplog.set_level(logging.WARNING)

        config_dict = {
            "version": "1.0.0",
            "root": {
                "TECO_VFD": {
                    "default_controls": [],
                    "instances": {
                        "1": {
                            "use_default_controls": False,
                            "controls": [
                                {
                                    "name": "Time Override High Priority",
                                    "code": "TIME_HIGH",
                                    "priority": 50,
                                    "active_time_ranges": [{"start": "09:00", "end": "12:00"}],
                                    "composite": {
                                        "any": [
                                            {
                                                "type": "threshold",
                                                "sources": [_src("TECO_VFD", "1", "RO_TEMPERATURE")],
                                                "operator": "gte",
                                                "threshold": 0.0,
                                            }
                                        ]
                                    },
                                    "actions": [
                                        {
                                            "model": "TECO_VFD",
                                            "slave_id": "1",
                                            "type": "set_frequency",
                                            "value": 30.0,
                                        }
                                    ],
                                }
                            ],
                        }
                    },
                }
            },
        }

        config = ControlConfig(**config_dict)
        assert config is not None
        assert "Recommend Time Override tier" in caplog.text

    def test_when_duplicate_priorities_exist_then_rules_are_deduplicated_by_priority_and_error_logged(self, caplog):
        caplog.set_level(logging.ERROR)

        config_dict = {
            "version": "1.0.0",
            "root": {
                "TECO_VFD": {
                    "default_controls": [],
                    "instances": {
                        "1": {
                            "use_default_controls": False,
                            "controls": [
                                {
                                    "name": "Rule A",
                                    "code": "RULE_A",
                                    "priority": 30,
                                    "composite": {
                                        "any": [
                                            {
                                                "type": "threshold",
                                                "sources": [_src("TECO_VFD", "1", "RO_TEMPERATURE")],
                                                "operator": "gt",
                                                "threshold": 25.0,
                                            }
                                        ]
                                    },
                                    "actions": [
                                        {
                                            "model": "TECO_VFD",
                                            "slave_id": "1",
                                            "type": "set_frequency",
                                            "value": 50.0,
                                        }
                                    ],
                                },
                                {
                                    "name": "Rule B",
                                    "code": "RULE_B",
                                    "priority": 30,
                                    "composite": {
                                        "any": [
                                            {
                                                "type": "threshold",
                                                "sources": [_src("TECO_VFD", "1", "RO_TEMPERATURE")],
                                                "operator": "gt",
                                                "threshold": 30.0,
                                            }
                                        ]
                                    },
                                    "actions": [
                                        {
                                            "model": "TECO_VFD",
                                            "slave_id": "1",
                                            "type": "set_frequency",
                                            "value": 60.0,
                                        }
                                    ],
                                },
                            ],
                        }
                    },
                }
            },
        }

        config = ControlConfig(**config_dict)
        rules = config.get_control_list("TECO_VFD", "1")

        assert len(rules) == 1
        assert rules[0].code == "RULE_B"
        assert "PRIORITY CONFLICT" in caplog.text

    def test_when_config_contains_invalid_rule_then_validation_error_is_raised(self):
        config_dict = {
            "version": "1.0.0",
            "root": {
                "TECO_VFD": {
                    "default_controls": [],
                    "instances": {
                        "1": {
                            "use_default_controls": False,
                            "controls": [
                                {
                                    "name": "Valid Emergency",
                                    "code": "VALID_EMERGENCY",
                                    "priority": 0,
                                    "composite": {
                                        "any": [
                                            {
                                                "type": "threshold",
                                                "sources": [_src("TECO_VFD", "1", "HZ")],
                                                "operator": "lte",
                                                "threshold": 30.0,
                                            }
                                        ]
                                    },
                                    "actions": [
                                        {
                                            "model": "TECO_VFD",
                                            "slave_id": "1",
                                            "type": "set_frequency",
                                            "emergency_override": True,
                                            "value": 60.0,
                                        }
                                    ],
                                },
                                {
                                    "name": "Invalid Emergency",
                                    "code": "INVALID_EMERGENCY",
                                    "priority": 50,
                                    "composite": {
                                        "any": [
                                            {
                                                "type": "threshold",
                                                "sources": [_src("TECO_VFD", "1", "HZ")],
                                                "operator": "lte",
                                                "threshold": 20.0,
                                            }
                                        ]
                                    },
                                    "actions": [
                                        {
                                            "model": "TECO_VFD",
                                            "slave_id": "1",
                                            "type": "set_frequency",
                                            "emergency_override": True,
                                            "value": 60.0,
                                        }
                                    ],
                                },
                            ],
                        }
                    },
                }
            },
        }

        with pytest.raises(ValidationError) as exc_info:
            ControlConfig(**config_dict)

        error_msg = str(exc_info.value)
        assert "INVALID_EMERGENCY" in error_msg or "controls" in error_msg


class TestActiveTimeRangesSemantics:
    def test_when_active_time_ranges_is_missing_then_rule_has_no_time_restriction(self):
        config_dict = {
            "version": "1.0.0",
            "root": {
                "TECO_VFD": {
                    "default_controls": [],
                    "instances": {
                        "1": {
                            "use_default_controls": False,
                            "controls": [
                                {
                                    "name": "No Time Restriction (missing field)",
                                    "code": "NO_TIME_MISSING",
                                    "priority": 10,
                                    "composite": {
                                        "any": [
                                            {
                                                "type": "threshold",
                                                "sources": [_src("TECO_VFD", "1", "HZ")],
                                                "operator": "gte",
                                                "threshold": 0.0,
                                            }
                                        ]
                                    },
                                    "actions": [
                                        {
                                            "model": "TECO_VFD",
                                            "slave_id": "1",
                                            "type": "set_frequency",
                                            "value": 30.0,
                                        }
                                    ],
                                }
                            ],
                        }
                    },
                }
            },
        }

        config = ControlConfig(**config_dict)
        rules = config.get_control_list("TECO_VFD", "1")
        assert len(rules) == 1
        assert rules[0].active_time_ranges in (None, [])

    def test_when_active_time_ranges_is_empty_list_then_rule_has_no_time_restriction(self):
        config_dict = {
            "version": "1.0.0",
            "root": {
                "TECO_VFD": {
                    "default_controls": [],
                    "instances": {
                        "1": {
                            "use_default_controls": False,
                            "controls": [
                                {
                                    "name": "No Time Restriction (empty list)",
                                    "code": "NO_TIME_EMPTY",
                                    "priority": 10,
                                    "active_time_ranges": [],
                                    "composite": {
                                        "any": [
                                            {
                                                "type": "threshold",
                                                "sources": [_src("TECO_VFD", "1", "HZ")],
                                                "operator": "gte",
                                                "threshold": 0.0,
                                            }
                                        ]
                                    },
                                    "actions": [
                                        {
                                            "model": "TECO_VFD",
                                            "slave_id": "1",
                                            "type": "set_frequency",
                                            "value": 30.0,
                                        }
                                    ],
                                }
                            ],
                        }
                    },
                }
            },
        }

        config = ControlConfig(**config_dict)
        rules = config.get_control_list("TECO_VFD", "1")
        assert len(rules) == 1
        assert rules[0].active_time_ranges in (None, [])
        assert not rules[0].active_time_ranges

    def test_when_active_time_ranges_has_values_then_rule_is_time_restricted(self):
        config_dict = {
            "version": "1.0.0",
            "root": {
                "TECO_VFD": {
                    "default_controls": [],
                    "instances": {
                        "1": {
                            "use_default_controls": False,
                            "controls": [
                                {
                                    "name": "Morning Fixed Frequency",
                                    "code": "TIME_RANGE_PRESENT",
                                    "priority": 10,
                                    "active_time_ranges": [{"start": "09:00", "end": "12:00"}],
                                    "composite": {
                                        "any": [
                                            {
                                                "type": "threshold",
                                                "sources": [_src("TECO_VFD", "1", "HZ")],
                                                "operator": "gte",
                                                "threshold": 0.0,
                                            }
                                        ]
                                    },
                                    "actions": [
                                        {
                                            "model": "TECO_VFD",
                                            "slave_id": "1",
                                            "type": "set_frequency",
                                            "value": 30.0,
                                        }
                                    ],
                                }
                            ],
                        }
                    },
                }
            },
        }

        config = ControlConfig(**config_dict)
        rules = config.get_control_list("TECO_VFD", "1")
        assert len(rules) == 1

        assert rules[0].active_time_ranges is not None
        assert len(rules[0].active_time_ranges) == 1
        assert rules[0].active_time_ranges[0].start == "09:00"
        assert rules[0].active_time_ranges[0].end == "12:00"

    def test_when_active_time_ranges_overlap_then_warning_is_logged_and_rule_is_kept(self, caplog):
        caplog.set_level(logging.WARNING)

        config_dict = {
            "version": "1.0.0",
            "root": {
                "TECO_VFD": {
                    "default_controls": [],
                    "instances": {
                        "1": {
                            "use_default_controls": False,
                            "controls": [
                                {
                                    "name": "Overlap Time Ranges",
                                    "code": "OVERLAP_TIME",
                                    "priority": 10,
                                    "active_time_ranges": [
                                        {"start": "09:00", "end": "17:00"},
                                        {"start": "10:00", "end": "12:00"},
                                    ],
                                    "composite": {
                                        "any": [
                                            {
                                                "type": "threshold",
                                                "sources": [_src("TECO_VFD", "1", "HZ")],
                                                "operator": "gt",
                                                "threshold": 0.0,
                                            }
                                        ]
                                    },
                                    "actions": [
                                        {"model": "TECO_VFD", "slave_id": "1", "type": "set_frequency", "value": 30.0}
                                    ],
                                }
                            ],
                        }
                    },
                }
            },
        }

        config = ControlConfig(**config_dict)
        rules = config.get_control_list("TECO_VFD", "1")

        assert len(rules) == 1
        assert rules[0].code == "OVERLAP_TIME"
        assert "overlap" in caplog.text.lower()

    def test_when_active_time_ranges_do_not_overlap_then_no_warning(self, caplog):
        caplog.set_level(logging.WARNING)

        config_dict = {
            "version": "1.0.0",
            "root": {
                "TECO_VFD": {
                    "default_controls": [],
                    "instances": {
                        "1": {
                            "use_default_controls": False,
                            "controls": [
                                {
                                    "name": "Non Overlap Time Ranges",
                                    "code": "NON_OVERLAP_TIME",
                                    "priority": 10,
                                    "active_time_ranges": [
                                        {"start": "09:00", "end": "10:00"},
                                        {"start": "10:00", "end": "12:00"},
                                    ],
                                    "composite": {
                                        "any": [
                                            {
                                                "type": "threshold",
                                                "sources": [_src("TECO_VFD", "1", "HZ")],
                                                "operator": "gt",
                                                "threshold": 0.0,
                                            }
                                        ]
                                    },
                                    "actions": [
                                        {"model": "TECO_VFD", "slave_id": "1", "type": "set_frequency", "value": 30.0}
                                    ],
                                }
                            ],
                        }
                    },
                }
            },
        }

        config = ControlConfig(**config_dict)
        _ = config.get_control_list("TECO_VFD", "1")

        assert "overlap" not in caplog.text.lower()
