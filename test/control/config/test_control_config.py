import logging

from control_config import ControlConfig
from model.control_model import ControlConditionModel


def _build_config(d):
    return ControlConfig.model_validate({"root": d})


def test_when_all_empty_then_skip_rule(caplog):
    caplog.set_level(logging.WARNING)
    config: ControlConfig = _build_config(
        {
            "SD400": {
                "default_controls": [],
                "instances": {
                    "7": {
                        "controls": [
                            {
                                "name": "BadAll",
                                "code": "BAD_ALL",
                                "priority": 10,
                                "composite": {"all": []},
                                "action": {"type": "turn_off"},
                            }
                        ]
                    }
                },
            }
        }
    )
    excepted_result = config.get_control_list("SD400", "7")
    assert excepted_result == []
    assert any("'all' must contain at least one child" in r.message for r in caplog.records)
    assert any("skip rule 'BAD_ALL': invalid composite" in r.message for r in caplog.records)


def test_when_not_has_list_then_skip_rule(caplog):
    caplog.set_level(logging.WARNING)
    config: ControlConfig = _build_config(
        {
            "SD400": {
                "default_controls": [],
                "instances": {
                    "7": {
                        "controls": [
                            {
                                "name": "BadNot",
                                "code": "BAD_NOT",
                                "priority": 10,
                                "composite": {
                                    "not": [{"type": "threshold", "source": "AIn01", "operator": "gt", "threshold": 30}]
                                },
                                "action": {"type": "turn_off"},
                            }
                        ]
                    }
                },
            }
        }
    )
    excepted_result = config.get_control_list("SD400", "7")
    assert excepted_result == []
    assert any("'not' must be a single CompositeNode" in r.message for r in caplog.records)


def test_when_difference_sources_len_not_2_then_skip_rule(caplog):
    caplog.set_level(logging.WARNING)
    config: ControlConfig = _build_config(
        {
            "SD400": {
                "default_controls": [],
                "instances": {
                    "7": {
                        "controls": [
                            {
                                "name": "BadDiff",
                                "code": "BAD_DIFF",
                                "priority": 10,
                                "composite": {
                                    "type": "difference",
                                    "sources": ["AIn01"],
                                    "operator": "gt",
                                    "threshold": 5,
                                },
                                "action": {"type": "turn_off"},
                            }
                        ]
                    }
                },
            }
        }
    )
    excepted_result = config.get_control_list("SD400", "7")
    assert excepted_result == []
    assert any("requires 'sources' of length 2" in r.message for r in caplog.records)


def test_when_threshold_between_missing_bounds_then_skip_rule(caplog):
    caplog.set_level(logging.WARNING)
    config: ControlConfig = _build_config(
        {
            "SD400": {
                "default_controls": [],
                "instances": {
                    "7": {
                        "controls": [
                            {
                                "name": "BadBetween",
                                "code": "BAD_BETWEEN",
                                "priority": 10,
                                "composite": {"type": "threshold", "source": "AIn03", "operator": "between"},
                                "action": {"type": "turn_off"},
                            }
                        ]
                    }
                },
            }
        }
    )
    excepted_result = config.get_control_list("SD400", "7")
    assert excepted_result == []
    assert any("requires 'min' and 'max'" in r.message for r in caplog.records)


def test_when_threshold_missing_source_then_skip_rule(caplog):
    caplog.set_level(logging.WARNING)
    config: ControlConfig = _build_config(
        {
            "SD400": {
                "default_controls": [],
                "instances": {
                    "7": {
                        "controls": [
                            {
                                "name": "BadThreshold",
                                "code": "BAD_THR",
                                "priority": 10,
                                "composite": {"type": "threshold", "operator": "gt", "threshold": 30},
                                "action": {"type": "turn_off"},
                            }
                        ]
                    }
                },
            }
        }
    )
    excepted_result = config.get_control_list("SD400", "7")
    assert excepted_result == []
    assert any("requires non-empty 'source'" in r.message for r in caplog.records)


def test_when_valid_rule_then_included(caplog):
    caplog.set_level(logging.WARNING)
    config: ControlConfig = _build_config(
        {
            "SD400": {
                "default_controls": [],
                "instances": {
                    "7": {
                        "controls": [
                            {
                                "name": "HighTemp",
                                "code": "HIGH_TEMP",
                                "priority": 80,
                                "composite": {
                                    "any": [
                                        {"type": "threshold", "source": "AIn01", "operator": "gt", "threshold": 40.0}
                                    ]
                                },
                                "action": {
                                    "type": "turn_off",
                                    "model": "TECO_VFD",
                                    "slave_id": "2",
                                    "target": "RW_ON_OFF",
                                },
                            }
                        ]
                    }
                },
            }
        }
    )
    excepted_result = config.get_control_list("SD400", "7")
    assert len(excepted_result) == 1
    assert excepted_result[0].code == "HIGH_TEMP"
    assert not any("Composite invalid" in r.message for r in caplog.records)


def test_when_valid_all_composite_rule_then_included():
    cfg = {
        "SD400": {
            "default_controls": [
                {
                    "name": "All Condition Example",
                    "code": "ALL_EX",
                    "priority": 30,
                    "composite": {
                        "all": [
                            {"type": "threshold", "source": "AIn01", "operator": "gt", "threshold": 40.0},
                            {"type": "difference", "sources": ["AIn01", "AIn02"], "operator": "gt", "threshold": 5.0},
                        ]
                    },
                    "action": {
                        "type": "turn_off",
                        "model": "TECO_VFD",
                        "slave_id": "2",
                        "target": "RW_ON_OFF",
                    },
                }
            ],
            "instances": {"3": {"use_default_controls": True}},
        }
    }
    config = _build_config(cfg)
    expected_result = config.get_control_list("SD400", "3")
    assert len(expected_result) == 1


def test_when_valid_any_composite_rule_then_included():
    cfg = {
        "SD400": {
            "default_controls": [
                {
                    "name": "Any Condition Example",
                    "code": "ANY_EX",
                    "priority": 20,
                    "composite": {
                        "any": [
                            {"type": "threshold", "source": "AIn01", "operator": "gt", "threshold": 40.0},
                            {"type": "threshold", "source": "AIn02", "operator": "lt", "threshold": 10.0},
                        ]
                    },
                    "action": {
                        "type": "turn_off",
                        "model": "TECO_VFD",
                        "slave_id": "2",
                        "target": "RW_ON_OFF",
                    },
                }
            ],
            "instances": {"3": {"use_default_controls": True}},
        }
    }
    config = _build_config(cfg)
    expected_result = config.get_control_list("SD400", "3")
    assert len(expected_result) == 1


def test_when_valid_not_composite_rule_then_included():
    cfg = {
        "SD400": {
            "default_controls": [],
            "instances": {
                "3": {
                    "controls": [
                        {
                            "name": "Not Condition Example",
                            "code": "NOT_EX",
                            "priority": 10,
                            "composite": {
                                "not": {
                                    "type": "threshold",
                                    "source": "AIn01",
                                    "operator": "gt",
                                    "threshold": 40.0,
                                }
                            },
                            "action": {
                                "type": "turn_off",
                                "model": "TECO_VFD",
                                "slave_id": "2",
                                "target": "RW_ON_OFF",
                            },
                        }
                    ]
                }
            },
        }
    }

    cfg_obj = _build_config(cfg)
    cond_list = cfg_obj.get_control_list("SD400", "3")
    assert len(cond_list) == 1
