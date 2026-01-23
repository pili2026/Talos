from core.evaluator.alert_evaluator import AlertEvaluationResult, AlertEvaluator
from core.model.enum.alert_enum import AlertSeverity
from core.model.enum.alert_state_enum import AlertState


def test_when_device_running_during_shutdown_then_trigger_alert(mock_alert_config_with_schedule, mock_time_evaluator):
    """Test alert triggered when device running outside work_hours"""
    # Arrange
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule,
        valid_device_ids={"TECO_VFD_1"},
        time_control_evaluator=mock_time_evaluator,
    )
    mock_time_evaluator.allow.return_value = False  # Outside work hours
    snapshot = {"RW_ON_OFF": 1.0}  # Device is ON

    # Act
    results = evaluator.evaluate("TECO_VFD_1", snapshot)

    # Assert
    assert len(results) == 1
    result = results[0]

    assert isinstance(result, AlertEvaluationResult)
    assert result.alert_code == "BLOWER_AFTER_HOURS"
    assert result.name == "Blower Running After Hours"
    assert result.device_name == "Main Blower VFD"
    assert result.severity == AlertSeverity.WARNING
    assert result.notification_type == AlertState.TRIGGERED.name
    assert result.condition == "schedule"
    assert result.threshold == 0  # expected_state
    assert result.current_value == 1.0  # actual state


def test_when_device_off_during_shutdown_then_no_alert(mock_alert_config_with_schedule, mock_time_evaluator):
    """Test no alert when device matches expected state during shutdown"""
    # Arrange
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule,
        valid_device_ids={"TECO_VFD_1"},
        time_control_evaluator=mock_time_evaluator,
    )
    mock_time_evaluator.allow.return_value = False  # Outside work hours
    snapshot = {"RW_ON_OFF": 0.0}  # Device is OFF (expected)

    # Act
    results = evaluator.evaluate("TECO_VFD_1", snapshot)

    # Assert
    assert len(results) == 0  # No alert triggered


def test_when_device_running_during_work_hours_then_no_alert(mock_alert_config_with_schedule, mock_time_evaluator):
    """Test no alert during work_hours (device allowed to run)"""
    # Arrange
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule,
        valid_device_ids={"TECO_VFD_1"},
        time_control_evaluator=mock_time_evaluator,
    )
    mock_time_evaluator.allow.return_value = True  # Inside work hours
    snapshot = {"RW_ON_OFF": 1.0}  # Device is ON

    # Act
    results = evaluator.evaluate("TECO_VFD_1", snapshot)

    # Assert
    assert len(results) == 0  # No alert during work hours


def test_when_critical_system_off_then_trigger_alert(mock_alert_config_with_schedule_expected_on, mock_time_evaluator):
    """Test alert for system that must always be ON"""
    # Arrange
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule_expected_on,
        valid_device_ids={"COOLING_1"},
        time_control_evaluator=mock_time_evaluator,
    )
    mock_time_evaluator.allow.return_value = False  # Outside work hours
    snapshot = {"RW_ON_OFF": 0.0}  # Device is OFF (unexpected)

    # Act
    results = evaluator.evaluate("COOLING_1", snapshot)

    # Assert
    assert len(results) == 1
    result = results[0]

    assert result.alert_code == "COOLING_MUST_RUN"
    assert result.device_name == "Critical Cooling System"
    assert result.severity == AlertSeverity.CRITICAL
    assert result.threshold == 1  # expected ON
    assert result.current_value == 0.0  # actual OFF


def test_when_time_evaluator_not_available_then_no_alert(mock_alert_config_with_schedule):
    """Test graceful handling when TimeControlEvaluator is not available"""
    # Arrange
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule,
        valid_device_ids={"TECO_VFD_1"},
        time_control_evaluator=None,  # No time evaluator
    )
    snapshot = {"RW_ON_OFF": 1.0}

    # Act
    results = evaluator.evaluate("TECO_VFD_1", snapshot)

    # Assert
    assert len(results) == 0  # Cannot evaluate without time control


def test_when_schedule_alert_resolved_then_correct_notification_type(
    mock_alert_config_with_schedule, mock_time_evaluator
):
    """Test RESOLVED notification when device returns to expected state"""
    # Arrange
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule,
        valid_device_ids={"TECO_VFD_1"},
        time_control_evaluator=mock_time_evaluator,
    )
    mock_time_evaluator.allow.return_value = False  # Outside work hours

    # First: Trigger alert (device ON when should be OFF)
    snapshot_triggered = {"RW_ON_OFF": 1.0}
    results_triggered = evaluator.evaluate("TECO_VFD_1", snapshot_triggered)
    assert len(results_triggered) == 1
    assert results_triggered[0].notification_type == AlertState.TRIGGERED.name

    # Second: Resolve alert (device returns to OFF)
    snapshot_resolved = {"RW_ON_OFF": 0.0}
    results_resolved = evaluator.evaluate("TECO_VFD_1", snapshot_resolved)
    assert len(results_resolved) == 1
    assert results_resolved[0].notification_type == AlertState.RESOLVED.name
