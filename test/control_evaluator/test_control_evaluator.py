import pytest

from evaluator.control_evaluator import ControlEvaluator
from model.control_model import (
    ControlActionModel,
    ControlActionType,
    ControlConditionModel,
)
from model.enum.condition_enum import ConditionOperator, ConditionType


def test_when_snapshot_value_exceeds_threshold_then_trigger_action(mock_control_config):
    # Arrange
    fake_action = ControlActionModel(
        type=ControlActionType.WRITE_DO,
        target="DO01",
        value=1,
    )

    fake_condition = ControlConditionModel(
        name="sd400_temp_high",
        code="TEMP_GT_30",
        type=ConditionType.THRESHOLD,
        operator=ConditionOperator.GREATER_THAN,
        threshold=30.0,
        source="TEMP",
        action=fake_action,
        priority=1,
    )

    mock_control_config.get_control_list.return_value = [fake_condition]
    evaluator = ControlEvaluator(mock_control_config)

    # Act
    result = evaluator.evaluate(model="SD400", slave_id="1", snapshot={"TEMP": 35.0})

    # Assert
    assert len(result) == 1
    assert result[0] == fake_action


def test_when_difference_between_sources_is_small_then_trigger_action(mock_control_config):
    # Arrange
    fake_action = ControlActionModel(
        type=ControlActionType.SET_FREQUENCY,
        target="FREQ_CTRL",
        value=50.0,
    )

    fake_condition = ControlConditionModel(
        name="teco_freq_diff_small",
        code="TECO_DIFF_LT_3",
        type=ConditionType.DIFFERENCE,
        operator=ConditionOperator.LESS_THAN,
        threshold=3.0,
        source=["Sensor1", "Sensor2"],
        action=fake_action,
        priority=2,
    )

    mock_control_config.get_control_list.return_value = [fake_condition]
    evaluator = ControlEvaluator(mock_control_config)

    # Act
    result = evaluator.evaluate(model="TECO_F510", slave_id="2", snapshot={"Sensor1": 10.0, "Sensor2": 12.5})

    # Assert
    assert len(result) == 1
    assert result[0] == fake_action


def test_when_snapshot_value_does_not_meet_condition_then_do_nothing(mock_control_config):
    # Arrange
    fake_action = ControlActionModel(
        type=ControlActionType.WRITE_DO,
        target="FAN",
        value=0,
    )

    fake_condition = ControlConditionModel(
        name="ima_c_temp_normal",
        code="TEMP_LT_25",
        type=ConditionType.THRESHOLD,
        operator=ConditionOperator.LESS_THAN,
        threshold=25.0,
        source="TEMP",
        action=fake_action,
        priority=1,
    )

    mock_control_config.get_control_list.return_value = [fake_condition]
    evaluator = ControlEvaluator(mock_control_config)

    # Act
    result = evaluator.evaluate(model="IMA_C", slave_id="3", snapshot={"TEMP": 30.0})

    # Assert
    assert result == []


def test_when_difference_source_is_invalid_then_raise_validation_error():
    # Arrange & Act & Assert
    fake_action = ControlActionModel(
        type=ControlActionType.RESET,
        target="VALVE",
        value=1,
    )

    with pytest.raises(ValueError, match="Difference condition must include exactly 2 sources"):
        ControlConditionModel(
            name="bad_diff_teco",
            code="BAD_TECO_DIFF",
            type=ConditionType.DIFFERENCE,
            operator=ConditionOperator.GREATER_THAN,
            threshold=1.0,
            source=["OnlyOneSource"],
            action=fake_action,
            priority=1,
        )


def test_when_sd400_uses_default_controls_then_trigger_if_condition_met(mock_control_config, freq_action_30hz):
    # Arrange
    fake_condition = ControlConditionModel(
        name="Temperature Difference Control",
        code="TEMP_DIFF_CTRL",
        priority=80,
        type=ConditionType.DIFFERENCE,
        source=["AIn01", "AIn02"],
        operator=ConditionOperator.GREATER_THAN,
        threshold=5.0,
        action=freq_action_30hz,
    )

    mock_control_config.get_control_list.return_value = [fake_condition]
    evaluator = ControlEvaluator(mock_control_config)

    # Act
    result = evaluator.evaluate("SD400", "3", {"AIn01": 30.0, "AIn02": 20.0})

    # Assert
    assert len(result) == 1
    assert result[0] == freq_action_30hz


def test_when_sd400_uses_default_controls_but_condition_not_met_then_do_nothing(
    mock_control_config, freq_action_30hz, snapshot_condition_not_met
):
    # Arrange
    fake_condition = ControlConditionModel(
        name="Temperature Difference Control",
        code="TEMP_DIFF_CTRL",
        priority=80,
        type=ConditionType.DIFFERENCE,
        source=["AIn01", "AIn02"],
        operator=ConditionOperator.GREATER_THAN,
        threshold=5.0,
        action=freq_action_30hz,
    )

    mock_control_config.get_control_list.return_value = [fake_condition]
    evaluator = ControlEvaluator(mock_control_config)

    # Act
    result = evaluator.evaluate("SD400", "3", snapshot_condition_not_met)

    # Assert
    assert result == []


def test_when_sd400_instance_has_custom_control_then_only_apply_instance_control(mock_control_config):
    # Arrange
    fake_action = ControlActionModel(
        model="IMA_C",
        slave_id=5,
        type=ControlActionType.WRITE_DO,
        target="DOut01",
        value=0,
    )

    fake_condition = ControlConditionModel(
        name="Close DO when hot",
        code="CLOSE_DO",
        type=ConditionType.THRESHOLD,
        source="AIn02",
        operator=ConditionOperator.GREATER_THAN,
        threshold=40.0,
        action=fake_action,
        priority=0,
    )

    mock_control_config.get_control_list.return_value = [fake_condition]
    evaluator = ControlEvaluator(mock_control_config)

    # Act
    result = evaluator.evaluate("SD400", "7", {"AIn02": 45.0})

    # Assert
    assert len(result) == 1
    assert result[0] == fake_action


def test_when_multiple_default_controls_trigger_then_return_actions_by_priority(
    mock_control_config, freq_action_30hz, freq_action_50hz, snapshot_all_high
):
    # Arrange
    high_priority_condition = ControlConditionModel(
        name="Pressure Control",
        code="PRESSURE_CTRL",
        priority=100,
        type=ConditionType.DIFFERENCE,
        source=["AIn03", "AIn04"],
        operator=ConditionOperator.GREATER_THAN,
        threshold=30.0,
        action=freq_action_50hz,
    )

    low_priority_condition = ControlConditionModel(
        name="Temperature Difference Control",
        code="TEMP_DIFF_CTRL",
        priority=80,
        type=ConditionType.DIFFERENCE,
        source=["AIn01", "AIn02"],
        operator=ConditionOperator.GREATER_THAN,
        threshold=5.0,
        action=freq_action_30hz,
    )

    mock_control_config.get_control_list.return_value = [low_priority_condition, high_priority_condition]
    evaluator = ControlEvaluator(mock_control_config)

    # Act
    result = evaluator.evaluate("SD400", "3", snapshot_all_high)

    # Assert
    assert len(result) == 1
    assert result[0] == freq_action_50hz


def test_when_only_one_of_multiple_controls_meets_condition_then_return_single_action(
    mock_control_config, freq_action_30hz, freq_action_50hz, snapshot_temp_trigger_only
):
    # Arrange
    triggered_condition = ControlConditionModel(
        name="Temperature Difference Control",
        code="TEMP_DIFF_CTRL",
        priority=80,
        type=ConditionType.DIFFERENCE,
        source=["AIn01", "AIn02"],
        operator=ConditionOperator.GREATER_THAN,
        threshold=5.0,
        action=freq_action_30hz,
    )

    skipped_condition = ControlConditionModel(
        name="Pressure Control",
        code="PRESSURE_CTRL",
        priority=100,
        type=ConditionType.DIFFERENCE,
        source=["AIn03", "AIn04"],
        operator=ConditionOperator.GREATER_THAN,
        threshold=30.0,
        action=freq_action_50hz,
    )

    mock_control_config.get_control_list.return_value = [triggered_condition, skipped_condition]
    evaluator = ControlEvaluator(mock_control_config)

    # Act
    result = evaluator.evaluate("SD400", "3", snapshot_temp_trigger_only)

    # Assert
    assert len(result) == 1
    assert result[0] == freq_action_30hz


def test_when_same_priority_then_pick_first_defined(
    mock_control_config, freq_action_30hz, freq_action_50hz, snapshot_all_same
):
    # Arrange
    index_one_condition = ControlConditionModel(
        name="R1",
        code="R1",
        priority=100,
        type=ConditionType.THRESHOLD,
        source="AIn01",
        operator=ConditionOperator.GREATER_THAN,
        threshold=1.0,
        action=freq_action_30hz,
    )
    index_two_condition = ControlConditionModel(
        name="R2",
        code="R2",
        priority=100,
        type=ConditionType.THRESHOLD,
        source="AIn02",
        operator=ConditionOperator.GREATER_THAN,
        threshold=1.0,
        action=freq_action_50hz,
    )
    mock_control_config.get_control_list.return_value = [index_one_condition, index_two_condition]
    evaluator = ControlEvaluator(mock_control_config)

    # Act
    result = evaluator.evaluate("SD400", "3", snapshot_all_same)

    # Assert
    assert len(result) == 1
    assert result[0] == freq_action_30hz


def test_when_only_lower_priority_matches_then_return_it(
    mock_control_config, freq_action_30hz, freq_action_50hz, snapshot_all_diff
):
    # Arrange
    priority_low = ControlConditionModel(
        name="LOW",
        code="LOW",
        priority=10,
        type=ConditionType.THRESHOLD,
        source="AIn01",
        operator=ConditionOperator.GREATER_THAN,
        threshold=1.0,
        action=freq_action_30hz,
    )
    priority_high = ControlConditionModel(
        name="HIGH",
        code="HIGH",
        priority=100,
        type=ConditionType.THRESHOLD,
        source="AIn02",
        operator=ConditionOperator.GREATER_THAN,
        threshold=999.0,
        action=freq_action_50hz,
    )
    mock_control_config.get_control_list.return_value = [priority_low, priority_high]
    evaluator = ControlEvaluator(mock_control_config)

    # Act
    result = evaluator.evaluate("SD400", "3", snapshot_all_diff)

    # Assert
    assert len(result) == 1
    assert result[0] == freq_action_30hz
