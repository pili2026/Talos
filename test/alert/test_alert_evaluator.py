from core.evaluator.alert_evaluator import AlertEvaluator
from core.model.enum.alert_enum import AlertSeverity
from core.model.enum.alert_state_enum import AlertState

# ============================================================
# Basic Threshold Alert Tests
# ============================================================


def test_when_threshold_exceeded_then_trigger_alert(mock_alert_config, valid_device_ids):
    """Test basic threshold alert triggering"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config, valid_device_ids)
    fake_snapshot = {"AIn01": 50.0}  # Above 49.0 threshold

    # Act
    results = evaluator.evaluate("SD400_3", fake_snapshot)

    # Assert
    assert len(results) == 1
    result = results[0]

    assert result.alert_code == "AIN01_HIGH"
    assert result.name == "AIn01 overheat"
    assert result.device_name == "SD400 Temperature Sensor"
    assert result.severity == AlertSeverity.WARNING
    assert result.condition == "gt"
    assert result.threshold == 49.0
    assert result.current_value == 50.0
    assert result.notification_type == AlertState.TRIGGERED.name


def test_when_threshold_not_exceeded_then_no_alert(mock_alert_config, valid_device_ids):
    """Test no alert when threshold not exceeded"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config, valid_device_ids)
    fake_snapshot = {"AIn01": 48.0}  # Below 49.0 threshold

    # Act
    results = evaluator.evaluate("SD400_3", fake_snapshot)

    # Assert
    assert len(results) == 0


def test_when_multiple_alerts_configured_then_evaluate_all(mock_alert_config, valid_device_ids):
    """Test multiple alerts for a single device"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config, valid_device_ids)
    fake_snapshot = {"ERROR": 1.0, "ALERT": 2.0}  # Both exceed threshold of 0

    # Act
    results = evaluator.evaluate("TECO_VFD_1", fake_snapshot)

    # Assert
    assert len(results) == 2
    alert_codes = {r.alert_code for r in results}
    assert "VFD_ERROR" in alert_codes
    assert "VFD_ALERT" in alert_codes


# ============================================================
# Aggregate Alert Tests
# ============================================================


def test_when_average_condition_met_then_trigger_average_alert(mock_alert_config_with_aggregate, valid_device_ids):
    """Test average aggregate type triggers when average exceeds threshold"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config_with_aggregate, valid_device_ids)
    fake_snapshot = {
        "AIn02": 39.0,
        "AIn03": 42.0,
        # Average = 40.5 > 40.0 threshold
    }

    # Act
    results = evaluator.evaluate("ADAM-4117_12", fake_snapshot)

    # Assert
    avg_alerts = [r for r in results if r.alert_code == "AVG_TEMP_HIGH"]
    assert len(avg_alerts) == 1

    result = avg_alerts[0]
    assert result.alert_code == "AVG_TEMP_HIGH"
    assert result.name == "Average Temperature High"
    assert result.device_name == "ADAM-4117 Multi-Point Sensor"
    assert result.condition == "gt"
    assert result.threshold == 40.0
    assert abs(result.current_value - 40.5) < 0.01  # Average of 39.0 and 42.0
    assert result.severity == AlertSeverity.CRITICAL
    assert result.message == "Average temperature across sensors exceeds threshold"


def test_when_sum_condition_met_then_trigger_sum_alert(mock_alert_config_with_aggregate, valid_device_ids):
    """Test sum aggregate type triggers when sum exceeds threshold"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config_with_aggregate, valid_device_ids)
    fake_snapshot = {
        "AIn02": 45.0,
        "AIn03": 40.0,
        # Sum = 85.0 > 80.0 threshold
    }

    # Act
    results = evaluator.evaluate("ADAM-4117_12", fake_snapshot)

    # Assert
    sum_alerts = [r for r in results if r.alert_code == "TOTAL_TEMP_HIGH"]
    assert len(sum_alerts) == 1

    result = sum_alerts[0]
    assert result.alert_code == "TOTAL_TEMP_HIGH"
    assert result.name == "Total Temperature High"
    assert result.device_name == "ADAM-4117 Multi-Point Sensor"
    assert result.condition == "gt"
    assert result.threshold == 80.0
    assert abs(result.current_value - 85.0) < 0.01  # Sum of 45.0 and 40.0
    assert result.severity == AlertSeverity.WARNING
    assert result.message == "Total temperature reading exceeds threshold"


def test_when_min_below_threshold_then_trigger_min_alert(mock_alert_config_with_aggregate, valid_device_ids):
    """Test min aggregate type triggers when minimum falls below threshold"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config_with_aggregate, valid_device_ids)
    fake_snapshot = {
        "AIn02": 18.0,
        "AIn03": 25.0,
        # Min = 18.0 < 20.0 threshold
    }

    # Act
    results = evaluator.evaluate("ADAM-4117_12", fake_snapshot)

    # Assert
    min_alerts = [r for r in results if r.alert_code == "MIN_TEMP_LOW"]
    assert len(min_alerts) == 1

    result = min_alerts[0]
    assert result.alert_code == "MIN_TEMP_LOW"
    assert result.name == "Minimum Temperature Low"
    assert result.device_name == "ADAM-4117 Multi-Point Sensor"
    assert result.condition == "lt"
    assert result.threshold == 20.0
    assert abs(result.current_value - 18.0) < 0.01
    assert result.severity == AlertSeverity.WARNING
    assert result.message == "Minimum temperature reading is too low"


def test_when_max_exceeds_threshold_then_trigger_max_alert(mock_alert_config_with_aggregate, valid_device_ids):
    """Test max aggregate type triggers when maximum exceeds threshold"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config_with_aggregate, valid_device_ids)
    fake_snapshot = {
        "AIn02": 40.0,
        "AIn03": 47.0,
        # Max = 47.0 > 45.0 threshold
    }

    # Act
    results = evaluator.evaluate("ADAM-4117_12", fake_snapshot)

    # Assert
    max_alerts = [r for r in results if r.alert_code == "MAX_TEMP_HIGH"]
    assert len(max_alerts) == 1

    result = max_alerts[0]
    assert result.alert_code == "MAX_TEMP_HIGH"
    assert result.name == "Maximum Temperature High"
    assert result.device_name == "ADAM-4117 Multi-Point Sensor"
    assert result.condition == "gt"
    assert result.threshold == 45.0
    assert abs(result.current_value - 47.0) < 0.01
    assert result.severity == AlertSeverity.CRITICAL
    assert result.message == "Maximum temperature reading exceeds threshold"


def test_when_multiple_aggregate_alerts_triggered_then_all_reported(mock_alert_config_with_aggregate, valid_device_ids):
    """Test multiple aggregate alerts can trigger simultaneously"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config_with_aggregate, valid_device_ids)
    fake_snapshot = {
        "AIn02": 50.0,
        "AIn03": 48.0,
        # Average = 49.0 > 40.0 ✓
        # Sum = 98.0 > 80.0 ✓
        # Min = 48.0 not < 20.0 ✗
        # Max = 50.0 > 45.0 ✓
    }

    # Act
    results = evaluator.evaluate("ADAM-4117_12", fake_snapshot)

    # Assert
    assert len(results) == 3  # AVG, SUM, MAX should trigger
    alert_codes = {r.alert_code for r in results}
    assert "AVG_TEMP_HIGH" in alert_codes
    assert "TOTAL_TEMP_HIGH" in alert_codes
    assert "MAX_TEMP_HIGH" in alert_codes
    assert "MIN_TEMP_LOW" not in alert_codes


# ============================================================
# Missing Data Tests
# ============================================================


def test_when_source_missing_then_no_alert(mock_alert_config, valid_device_ids):
    """Test graceful handling of missing source data"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config, valid_device_ids)
    fake_snapshot = {}  # Missing AIn01

    # Act
    results = evaluator.evaluate("SD400_3", fake_snapshot)

    # Assert
    assert len(results) == 0  # Cannot evaluate without source data


def test_when_partial_aggregate_sources_missing_then_no_alert(mock_alert_config_with_aggregate, valid_device_ids):
    """Test aggregate alerts require all sources"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config_with_aggregate, valid_device_ids)
    fake_snapshot = {"AIn02": 50.0}  # Missing AIn03

    # Act
    results = evaluator.evaluate("ADAM-4117_12", fake_snapshot)

    # Assert
    assert len(results) == 0  # Cannot calculate aggregate without all sources


# ============================================================
# Invalid Device Tests
# ============================================================


def test_when_device_not_in_config_then_no_alert(mock_alert_config, valid_device_ids):
    """Test no alerts for devices not in configuration"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config, valid_device_ids)
    fake_snapshot = {"AIn01": 50.0}

    # Act
    results = evaluator.evaluate("UNKNOWN_MODEL_99", fake_snapshot)

    # Assert
    assert len(results) == 0


def test_when_device_id_invalid_format_then_no_alert(mock_alert_config, valid_device_ids):
    """Test graceful handling of invalid device ID format"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config, valid_device_ids)
    fake_snapshot = {"AIn01": 50.0}

    # Act
    results = evaluator.evaluate("INVALID_DEVICE_ID", fake_snapshot)

    # Assert
    assert len(results) == 0


# ============================================================
# State Management Tests
# ============================================================


def test_when_alert_triggered_twice_then_only_first_notifies(mock_alert_config, valid_device_ids):
    """Test deduplication of consecutive triggered alerts"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config, valid_device_ids)
    fake_snapshot = {"AIn01": 50.0}

    # Act - First trigger
    results_first = evaluator.evaluate("SD400_3", fake_snapshot)
    assert len(results_first) == 1
    assert results_first[0].notification_type == AlertState.TRIGGERED.name

    # Act - Second trigger (same condition)
    results_second = evaluator.evaluate("SD400_3", fake_snapshot)

    # Assert - Should not notify again
    assert len(results_second) == 0


def test_when_alert_resolves_then_sends_resolved_notification(mock_alert_config, valid_device_ids):
    """Test RESOLVED notification when condition clears"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config, valid_device_ids)

    # Act - Trigger alert
    snapshot_triggered = {"AIn01": 50.0}
    results_triggered = evaluator.evaluate("SD400_3", snapshot_triggered)
    assert len(results_triggered) == 1
    assert results_triggered[0].notification_type == AlertState.TRIGGERED.name

    # Act - Resolve alert
    snapshot_resolved = {"AIn01": 48.0}
    results_resolved = evaluator.evaluate("SD400_3", snapshot_resolved)

    # Assert
    assert len(results_resolved) == 1
    result = results_resolved[0]
    assert result.notification_type == AlertState.RESOLVED.name
    assert result.alert_code == "AIN01_HIGH"


def test_when_alert_re_triggers_after_resolution_then_notifies(mock_alert_config, valid_device_ids):
    """Test alert can re-trigger after being resolved"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config, valid_device_ids)

    # Trigger → Resolve → Re-trigger
    evaluator.evaluate("SD400_3", {"AIn01": 50.0})  # Trigger
    evaluator.evaluate("SD400_3", {"AIn01": 48.0})  # Resolve
    evaluator.evaluate("SD400_3", {"AIn01": 48.0})  # Clear resolved state

    # Act - Re-trigger
    results = evaluator.evaluate("SD400_3", {"AIn01": 50.0})

    # Assert
    assert len(results) == 1
    assert results[0].notification_type == AlertState.TRIGGERED.name


# ============================================================
# Condition Operator Tests
# ============================================================


def test_when_using_less_than_operator_then_triggers_correctly(mock_alert_config, valid_device_ids):
    """Test less than (<) operator"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config, valid_device_ids)
    fake_snapshot = {"AIn02": 4.0}  # Below 5.0 threshold

    # Act
    results = evaluator.evaluate("SD400_7", fake_snapshot)

    # Assert
    assert len(results) == 1
    result = results[0]
    assert result.alert_code == "AIN02_LOW"
    assert result.condition == "lt"
    assert result.current_value == 4.0
    assert result.threshold == 5.0


def test_when_different_conditions_for_same_source_then_evaluate_independently(
    mock_alert_config_with_aggregate, valid_device_ids
):
    """Test multiple conditions on same sources evaluate independently"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config_with_aggregate, valid_device_ids)
    fake_snapshot = {
        "AIn02": 15.0,
        "AIn03": 16.0,
        # Average = 15.5 < 40.0 (AVG_TEMP_HIGH not triggered)
        # Min = 15.0 < 20.0 (MIN_TEMP_LOW triggered)
    }

    # Act
    results = evaluator.evaluate("ADAM-4117_12", fake_snapshot)

    # Assert
    assert len(results) == 1
    assert results[0].alert_code == "MIN_TEMP_LOW"


# ============================================================
# Initialization Tests
# ============================================================


def test_when_unknown_device_in_config_then_logs_warning(mock_alert_config_with_unknown_device, caplog):
    """Test initialization handles unknown devices gracefully"""
    # Arrange & Act
    with caplog.at_level("WARNING"):
        evaluator = AlertEvaluator(
            mock_alert_config_with_unknown_device, valid_device_ids={"SD400_3"}  # Does not include SD400_999
        )

    # Assert
    assert "SD400_999" in caplog.text
    assert "SKIP" in caplog.text or "Unknown" in caplog.text
