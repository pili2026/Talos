import math

import pytest

from model.enum.condition_enum import ControlActionType


def test_when_single_threshold_via_any_result_action_triggered(make_config, make_evaluator, make_snapshot):
    # Arrange
    control_config = {
        "name": "High Temperature",
        "code": "HIGH_TEMP",
        "priority": 80,
        "composite": {"any": [{"type": "threshold", "source": "AIn01", "operator": "gt", "threshold": 40.0}]},
        "action": {"type": "turn_off", "model": "TECO_VFD", "slave_id": "2", "target": "RW_ON_OFF"},
    }
    config_dict = make_config("SD400", "1", [control_config])
    evaluator, model, slave_id = make_evaluator(config_dict)
    snapshot = make_snapshot(AIn01=41.0)

    # Act
    expected_result = evaluator.evaluate(model, slave_id, snapshot)

    # Assert
    assert len(expected_result) == 1
    assert expected_result[0].type == ControlActionType.TURN_OFF


def test_when_not_condition_inner_false_result_action_triggered(make_config, make_evaluator, make_snapshot):
    """
    Case: AIn01 = 39 → threshold(39 > 40) = False → not False = True → action triggered
    """
    # Arrange
    control_config = {
        "name": "Not Example",
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
    config_dict = make_config("SD400", "1", [control_config])
    evaluator, model, slave_id = make_evaluator(config_dict)
    snapshot = make_snapshot(AIn01=39.0)  # 39 ≤ 40 → Triggered

    # Act
    expected_result = evaluator.evaluate(model, slave_id, snapshot)

    # Assert
    assert len(expected_result) == 1
    assert expected_result[0].type == ControlActionType.TURN_OFF
    # TODO: Wait to improve ControlActionModel to include 'code' field
    # assert expected_result[0].code == "NOT_EX"


def test_when_not_condition_inner_true_result_no_action(make_config, make_evaluator, make_snapshot):
    """
    Case: AIn01 = 41 → threshold(41 > 40) = True → not True = False → no action
    """
    # Arrange
    control_config = {
        "name": "Not Example",
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
    config_dict = make_config("SD400", "1", [control_config])
    evaluator, model, slave_id = make_evaluator(config_dict)
    snapshot = make_snapshot(AIn01=41.0)  # 41 > 40 → Not triggered

    # Act
    expected_result = evaluator.evaluate(model, slave_id, snapshot)

    # Assert
    assert expected_result == []


def test_when_difference_abs_gt_threshold_result_action_triggered(make_config, make_evaluator, make_snapshot):
    # Arrange
    control_config = {
        "name": "Delta T",
        "code": "DT_GT_5",
        "priority": 90,
        "composite": {
            "all": [
                {"type": "difference", "sources": ["AIn01", "AIn02"], "operator": "gt", "threshold": 5.0, "abs": True}
            ]
        },
        "action": {"type": "set_frequency", "model": "TECO_VFD", "slave_id": "2", "target": "RW_HZ", "value": 45.0},
    }
    config_dict = make_config("SD400", "1", [control_config])
    evaluator, model, slave_id = make_evaluator(config_dict)
    snapshot = make_snapshot(AIn01=46.0, AIn02=40.0)

    # Act
    expected_result = evaluator.evaluate(model, slave_id, snapshot)

    # Assert
    assert len(expected_result) == 1
    assert expected_result[0].type == ControlActionType.SET_FREQUENCY
    assert expected_result[0].value == 45.0

    # TODO: Wait to improve ControlActionModel to include 'code' field
    # assert expected_result[0].code == "DT_GT_5"


def test_when_threshold_between_inclusive_bounds_result_action_triggered(make_config, make_evaluator, make_snapshot):
    # Arrange
    control_config = {
        "name": "Pressure Window",
        "code": "PRESS_BETWEEN",
        "priority": 50,
        "composite": {"any": [{"type": "threshold", "source": "AIn03", "operator": "between", "min": 3.0, "max": 5.0}]},
        "action": {"type": "turn_on", "model": "TECO_VFD", "slave_id": "2", "target": "RW_ON_OFF"},
    }
    config_dict = make_config("SD400", "1", [control_config])
    evaluator, model, slave_id = make_evaluator(config_dict)
    snapshot = make_snapshot(AIn03=3.0)

    # Act
    expected_result = evaluator.evaluate(model, slave_id, snapshot)

    # Assert
    assert len(expected_result) == 1
    assert expected_result[0].type == "turn_on"


def test_when_multiple_matches_different_priorities_result_pick_highest(make_config, make_evaluator, make_snapshot):
    # Arrange
    control_config_list = [
        {
            "name": "Low Priority",
            "code": "LOW",
            "priority": 80,
            "composite": {"any": [{"type": "threshold", "source": "AIn01", "operator": "gt", "threshold": 40.0}]},
            "action": {"type": "turn_on", "model": "TECO_VFD", "slave_id": "2", "target": "RW_ON_OFF"},
        },
        {
            "name": "High Priority",
            "code": "HIGH",
            "priority": 100,
            "composite": {
                "any": [{"type": "threshold", "source": "AIn03", "operator": "between", "min": 3.0, "max": 5.0}]
            },
            "action": {"type": "set_frequency", "model": "TECO_VFD", "slave_id": "2", "target": "RW_HZ", "value": 45.0},
        },
    ]
    config_dict = make_config("SD400", "1", control_config_list)
    evaluator, model, slave_id = make_evaluator(config_dict)
    snapshot = make_snapshot(AIn01=41.0, AIn03=4.0)

    # Act
    expected_result = evaluator.evaluate(model, slave_id, snapshot)

    # Assert
    assert len(expected_result) == 1

    # TODO: Wait to improve ControlActionModel to include 'code' field
    # assert expected_result[0].code == "HIGH"


def test_when_multiple_matches_same_priority_result_keep_first_defined(make_config, make_evaluator, make_snapshot):
    # Arrange
    control_config = [
        {
            "name": "First",
            "code": "FIRST",
            "priority": 100,
            "composite": {"any": [{"type": "threshold", "source": "AIn01", "operator": "gt", "threshold": 40.0}]},
            "action": {"type": "turn_on", "model": "TECO_VFD", "slave_id": "2", "target": "RW_ON_OFF"},
        },
        {
            "name": "Second",
            "code": "SECOND",
            "priority": 100,
            "composite": {
                "any": [{"type": "threshold", "source": "AIn03", "operator": "between", "min": 3.0, "max": 5.0}]
            },
            "action": {"type": "set_frequency", "model": "TECO_VFD", "slave_id": "2", "target": "RW_HZ", "value": 45.0},
        },
    ]
    config_dict = make_config("SD400", "1", control_config)
    evaluator, model, slave_id = make_evaluator(config_dict)
    snapshot = make_snapshot(AIn01=41.0, AIn03=4.0)

    # Act
    expected_result = evaluator.evaluate(model, slave_id, snapshot)

    # Assert
    assert len(expected_result) == 1

    # TODO: Wait to improve ControlActionModel to include 'code' field
    # assert expected_result[0].code == "FIRST"


def test_when_invalid_composite_structure_result_skipped(make_config, make_evaluator, make_snapshot):
    # Arrange
    control_config = {
        "name": "Invalid Difference",
        "code": "INV_DIFF",
        "priority": 10,
        "composite": {
            "all": [{"type": "difference", "sources": ["AIn01"], "operator": "gt", "threshold": 5.0}]  # invalid
        },
        "action": {"type": "turn_off", "model": "TECO_VFD", "slave_id": "2", "target": "RW_ON_OFF"},
    }
    config_dict = make_config("SD400", "1", [control_config])
    evaluator, model, slave_id = make_evaluator(config_dict)
    snapshot = make_snapshot(AIn01=10.0)

    # Act
    expected_result = evaluator.evaluate(model, slave_id, snapshot)

    # Assert
    assert expected_result == []


@pytest.mark.parametrize("snapshot", [{"AIn01": math.nan}, {}])
def test_when_value_is_nan_or_missing_result_skipped(make_config, make_evaluator, snapshot):
    # Arrange
    control_config = {
        "name": "GT 40",
        "code": "GT40",
        "priority": 20,
        "composite": {"any": [{"type": "threshold", "source": "AIn01", "operator": "gt", "threshold": 40.0}]},
        "action": {"type": "turn_on", "model": "TECO_VFD", "slave_id": "2", "target": "RW_ON_OFF"},
    }
    config_dict = make_config("SD400", "1", [control_config])
    evaluator, model, slave_id = make_evaluator(config_dict)

    # Act
    expected_result = evaluator.evaluate(model, slave_id, snapshot)

    # Assert
    assert expected_result == []
