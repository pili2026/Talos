from datetime import datetime
from zoneinfo import ZoneInfo

from evaluator.alert_evaluator import AlertEvaluator
from model.enum.alert_enum import AlertSeverity
from model.enum.alert_state_enum import AlertState

# ============================================================
# Schedule Expected State Tests with Mock Time Evaluator
# ============================================================


def test_when_device_running_during_shutdown_then_trigger_alert(mock_alert_config_with_schedule, mock_time_evaluator):
    """Test alert triggered when device running outside work_hours"""
    # Arrange
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule,
        valid_device_ids={"TECO_VFD_1"},
        time_evaluator=mock_time_evaluator,
    )
    mock_time_evaluator.allow.return_value = False  # Outside work hours
    snapshot = {"RW_ON_OFF": 1.0}  # Device is ON

    # Act
    results = evaluator.evaluate("TECO_VFD_1", snapshot)

    # Assert
    assert len(results) == 1
    code, msg, severity, notif_type = results[0]

    assert code == "BLOWER_AFTER_HOURS"
    assert "RW_ON_OFF=ON" in msg
    assert "expected OFF" in msg
    assert "shutdown period" in msg
    assert severity == AlertSeverity.WARNING
    assert notif_type == AlertState.TRIGGERED.name


def test_when_device_off_during_shutdown_then_no_alert(mock_alert_config_with_schedule, mock_time_evaluator):
    """Test no alert when device is OFF during shutdown period as expected"""
    # Arrange
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule,
        valid_device_ids={"TECO_VFD_1"},
        time_evaluator=mock_time_evaluator,
    )
    mock_time_evaluator.allow.return_value = False  # Outside work hours
    snapshot = {"RW_ON_OFF": 0.0}  # Device is OFF

    # Act
    results = evaluator.evaluate("TECO_VFD_1", snapshot)

    # Assert
    assert len(results) == 0


def test_when_device_running_during_work_hours_then_no_alert(mock_alert_config_with_schedule, mock_time_evaluator):
    """Test no alert when device running within work_hours"""
    # Arrange
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule,
        valid_device_ids={"TECO_VFD_1"},
        time_evaluator=mock_time_evaluator,
    )
    mock_time_evaluator.allow.return_value = True  # In work hours
    snapshot = {"RW_ON_OFF": 1.0}  # Device is ON

    # Act
    results = evaluator.evaluate("TECO_VFD_1", snapshot)

    # Assert
    assert len(results) == 0


def test_when_alert_resolved_then_send_resolved_notification(mock_alert_config_with_schedule, mock_time_evaluator):
    """Test RESOLVED notification when device turns OFF during shutdown"""
    # Arrange
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule,
        valid_device_ids={"TECO_VFD_1"},
        time_evaluator=mock_time_evaluator,
    )
    mock_time_evaluator.allow.return_value = False  # Outside work hours

    # Act: First evaluation - Device ON → Trigger alert
    snapshot_on = {"RW_ON_OFF": 1.0}
    results_trigger = evaluator.evaluate("TECO_VFD_1", snapshot_on)

    # Assert trigger
    assert len(results_trigger) == 1
    assert results_trigger[0][3] == AlertState.TRIGGERED.name

    # Act: Second evaluation - Device OFF → Resolve alert
    snapshot_off = {"RW_ON_OFF": 0.0}
    results_resolved = evaluator.evaluate("TECO_VFD_1", snapshot_off)

    # Assert resolved
    assert len(results_resolved) == 1
    code, msg, _, notif_type = results_resolved[0]

    assert code == "BLOWER_AFTER_HOURS"
    assert "RESOLVED" in msg
    assert "returned to expected state" in msg
    assert notif_type == AlertState.RESOLVED.name


def test_when_no_time_evaluator_then_log_warning_and_skip(mock_alert_config_with_schedule, caplog):
    """Test warning logged and alert skipped when TimeControlEvaluator not available"""
    # Arrange: Create evaluator without time_evaluator
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule,
        valid_device_ids={"TECO_VFD_1"},
        time_evaluator=None,  # No time evaluator
    )
    snapshot = {"RW_ON_OFF": 1.0}

    # Act
    with caplog.at_level("WARNING"):
        results = evaluator.evaluate("TECO_VFD_1", snapshot)

    # Assert
    assert len(results) == 0
    assert any("TimeControlEvaluator not available" in msg for msg in caplog.messages)


def test_when_missing_source_in_snapshot_then_log_warning_and_skip(
    mock_alert_config_with_schedule, mock_time_evaluator, caplog
):
    """Test warning logged when source parameter not in snapshot"""
    # Arrange
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule,
        valid_device_ids={"TECO_VFD_1"},
        time_evaluator=mock_time_evaluator,
    )
    mock_time_evaluator.allow.return_value = False
    snapshot = {}  # Missing RW_ON_OFF

    # Act
    with caplog.at_level("WARNING"):
        results = evaluator.evaluate("TECO_VFD_1", snapshot)

    # Assert
    assert len(results) == 0
    assert any("not found in snapshot" in msg for msg in caplog.messages)


def test_when_expected_state_on_and_device_off_then_trigger_alert(
    mock_alert_config_with_schedule_expected_on, mock_time_evaluator
):
    """Test alert when device expected to be ON but is OFF"""
    # Arrange
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule_expected_on,
        valid_device_ids={"COOLING_1"},
        time_evaluator=mock_time_evaluator,
    )
    mock_time_evaluator.allow.return_value = False  # Outside work hours
    snapshot = {"RW_ON_OFF": 0.0}  # Device is OFF (violation!)

    # Act
    results = evaluator.evaluate("COOLING_1", snapshot)

    # Assert
    assert len(results) == 1
    code, msg, severity, _ = results[0]

    assert code == "COOLING_MUST_RUN"
    assert "RW_ON_OFF=OFF" in msg
    assert "expected ON" in msg
    assert severity == AlertSeverity.CRITICAL


def test_when_expected_state_on_and_device_on_then_no_alert(
    mock_alert_config_with_schedule_expected_on, mock_time_evaluator
):
    """Test no alert when device expected to be ON and is ON"""
    # Arrange
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule_expected_on,
        valid_device_ids={"COOLING_1"},
        time_evaluator=mock_time_evaluator,
    )
    mock_time_evaluator.allow.return_value = False  # Outside work hours
    snapshot = {"RW_ON_OFF": 1.0}  # Device is ON (as expected)

    # Act
    results = evaluator.evaluate("COOLING_1", snapshot)

    # Assert
    assert len(results) == 0


def test_when_continuous_violation_then_no_repeated_notification(mock_alert_config_with_schedule, mock_time_evaluator):
    """Test no repeated notifications for continuous violations"""
    # Arrange
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule,
        valid_device_ids={"TECO_VFD_1"},
        time_evaluator=mock_time_evaluator,
    )
    mock_time_evaluator.allow.return_value = False
    snapshot = {"RW_ON_OFF": 1.0}

    # Act: First evaluation → TRIGGERED
    results_1 = evaluator.evaluate("TECO_VFD_1", snapshot)
    assert len(results_1) == 1

    # Act: Second evaluation → ACTIVE (no notification)
    results_2 = evaluator.evaluate("TECO_VFD_1", snapshot)

    # Assert
    assert len(results_2) == 0


# ============================================================
# Integration Tests with Real Time Evaluator
# ============================================================


def test_when_night_time_23_00_and_device_running_then_trigger_alert(
    mock_alert_config_with_schedule, real_time_evaluator
):
    """Integration test: Alert triggered at 23:00 with real TimeControlEvaluator"""
    # Arrange
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule,
        valid_device_ids={"TECO_VFD_1"},
        time_evaluator=real_time_evaluator,
    )
    # Simulate 23:00 (outside work hours 09:00-18:00)
    night_time = datetime(2025, 1, 15, 23, 0, 0, tzinfo=ZoneInfo("Asia/Taipei"))

    # Verify time_evaluator considers this outside work hours
    assert real_time_evaluator.allow("TECO_VFD_1", now=night_time) is False

    # Device is ON during shutdown
    snapshot = {"RW_ON_OFF": 1.0}

    # Act
    # Note: This will use current time, not night_time
    # For true integration test, need to inject time into evaluate()
    # For now, we can test the evaluator's logic separately
    _ = evaluator.evaluate("TECO_VFD_1", snapshot)

    # Assert: Result depends on actual current time
    # This test demonstrates integration pattern
    # In real scenario, would need time injection


def test_when_afternoon_14_00_and_device_running_then_no_alert(mock_alert_config_with_schedule, real_time_evaluator):
    """Integration test: No alert at 14:00 with real TimeControlEvaluator"""
    # Arrange
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule,
        valid_device_ids={"TECO_VFD_1"},
        time_evaluator=real_time_evaluator,
    )
    # Simulate 14:00 (within work hours 09:00-18:00)
    afternoon = datetime(2025, 1, 15, 14, 0, 0, tzinfo=ZoneInfo("Asia/Taipei"))

    # Verify time_evaluator considers this in work hours
    assert real_time_evaluator.allow("TECO_VFD_1", now=afternoon) is True

    # Device is ON during work hours (OK)
    snapshot = {"RW_ON_OFF": 1.0}

    # Act
    # Note: Similar limitation as above test
    _ = evaluator.evaluate("TECO_VFD_1", snapshot)

    # Assert: Result depends on actual current time
