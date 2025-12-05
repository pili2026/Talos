from core.evaluator.alert_evaluator import AlertEvaluator

# ============================================================
# Existing Tests (Updated for sources format)
# ============================================================


def test_when_device_has_custom_alert_then_trigger_alert_if_condition_met(mock_alert_config, valid_device_ids):
    """Test custom alert triggers when condition is met"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config, valid_device_ids)
    fake_snapshot = {"AIn02": 3.0}

    # Act
    results = evaluator.evaluate("SD400_7", fake_snapshot)

    # Assert
    assert len(results) == 1
    assert results[0][0] == "AIN02_LOW"
    assert "AIn02" in results[0][1]


def test_when_device_uses_default_alerts_then_fallback_and_trigger_if_condition_met(
    mock_alert_config, valid_device_ids
):
    """Test default alerts are used when use_default_alerts is True"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config, valid_device_ids)
    fake_snapshot = {"AIn01": 51.0}

    # Act
    results = evaluator.evaluate("SD400_3", fake_snapshot)

    # Assert
    assert len(results) == 1
    assert results[0][0] == "AIN01_HIGH"
    assert "AIn01" in results[0][1]


def test_when_device_has_no_alerts_then_return_empty(mock_alert_config, valid_device_ids):
    """Test no alerts triggered when device has no alert config"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config, valid_device_ids)
    fake_snapshot = {"AIn01": 60.0}

    # Act
    results = evaluator.evaluate("SD400_9", fake_snapshot)

    # Assert
    assert len(results) == 0


def test_when_snapshot_missing_alert_source_then_log_warning_and_skip(mock_alert_config, caplog, valid_device_ids):
    """Test warning logged and alert skipped when source is missing from snapshot"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config, valid_device_ids)
    fake_snapshot = {"AIn03": 60.0}  # Missing AIn01

    # Act
    with caplog.at_level("WARNING"):
        results = evaluator.evaluate("SD400_3", fake_snapshot)

    # Assert
    assert len(results) == 0
    # Updated message format to match new evaluator
    assert any("Missing sources" in msg and "AIn01" in msg for msg in caplog.messages)


def test_when_alert_config_target_device_not_found_then_skip(mock_alert_config_with_unknown_device, caplog):
    """Test unknown device is skipped during initialization"""
    # Arrange
    fake_valid_device_ids = {"SD400_3"}

    # Act
    with caplog.at_level("WARNING", logger="AlertEvaluator"):
        evaluator = AlertEvaluator(mock_alert_config_with_unknown_device, fake_valid_device_ids)

    # Assert
    assert "SD400_999" not in evaluator.device_alert_dict.get("SD400", {})
    assert any("[SKIP] Unknown device in config: SD400_999" in msg for msg in caplog.messages)


# ============================================================
# New Tests for Aggregate Functionality
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
    avg_alerts = [r for r in results if r[0] == "AVG_TEMP_HIGH"]
    assert len(avg_alerts) == 1
    assert "AVG_TEMP_HIGH" == avg_alerts[0][0]
    assert "average(AIn02, AIn03)" in avg_alerts[0][1]
    assert "40.5" in avg_alerts[0][1] or "40.50" in avg_alerts[0][1]


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
    sum_alerts = [r for r in results if r[0] == "TOTAL_TEMP_HIGH"]
    assert len(sum_alerts) == 1
    assert "TOTAL_TEMP_HIGH" == sum_alerts[0][0]
    assert "sum(AIn02, AIn03)" in sum_alerts[0][1]
    assert "85" in sum_alerts[0][1]


def test_when_min_condition_met_then_trigger_min_alert(mock_alert_config_with_aggregate, valid_device_ids):
    """Test min aggregate type triggers when minimum is below threshold"""
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
    min_alerts = [r for r in results if r[0] == "MIN_TEMP_LOW"]
    assert len(min_alerts) == 1
    assert "MIN_TEMP_LOW" == min_alerts[0][0]
    assert "min(AIn02, AIn03)" in min_alerts[0][1]
    assert "18" in min_alerts[0][1]


def test_when_max_condition_met_then_trigger_max_alert(mock_alert_config_with_aggregate, valid_device_ids):
    """Test max aggregate type triggers when maximum exceeds threshold"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config_with_aggregate, valid_device_ids)
    fake_snapshot = {
        "AIn02": 42.0,
        "AIn03": 47.0,
        # Max = 47.0 > 45.0 threshold
    }

    # Act
    results = evaluator.evaluate("ADAM-4117_12", fake_snapshot)

    # Assert
    max_alerts = [r for r in results if r[0] == "MAX_TEMP_HIGH"]
    assert len(max_alerts) == 1
    assert "MAX_TEMP_HIGH" == max_alerts[0][0]
    assert "max(AIn02, AIn03)" in max_alerts[0][1]
    assert "47" in max_alerts[0][1]


def test_when_aggregate_missing_source_then_skip_alert(mock_alert_config_with_aggregate, caplog, valid_device_ids):
    """Test aggregate alert is skipped when one of the sources is missing"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config_with_aggregate, valid_device_ids)
    fake_snapshot = {
        "AIn02": 45.0,
        # Missing AIn03
    }

    # Act
    with caplog.at_level("WARNING"):
        results = evaluator.evaluate("ADAM-4117_12", fake_snapshot)

    # Assert
    assert len(results) == 0
    assert any("Missing sources" in msg and "AIn03" in msg for msg in caplog.messages)


def test_when_multiple_aggregate_alerts_triggered_then_return_all(mock_alert_config_with_aggregate, valid_device_ids):
    """Test multiple aggregate alerts can trigger simultaneously"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config_with_aggregate, valid_device_ids)
    fake_snapshot = {
        "AIn02": 46.0,
        "AIn03": 47.0,
        # Average = 46.5 > 40.0 ✓
        # Sum = 93.0 > 80.0 ✓
        # Min = 46.0 > 20.0 ✗
        # Max = 47.0 > 45.0 ✓
    }

    # Act
    results = evaluator.evaluate("ADAM-4117_12", fake_snapshot)

    # Assert
    assert len(results) == 3  # AVG_TEMP_HIGH, TOTAL_TEMP_HIGH, MAX_TEMP_HIGH
    alert_codes = {r[0] for r in results}
    assert "AVG_TEMP_HIGH" in alert_codes
    assert "TOTAL_TEMP_HIGH" in alert_codes
    assert "MAX_TEMP_HIGH" in alert_codes
    assert "MIN_TEMP_LOW" not in alert_codes


def test_when_average_exactly_at_threshold_then_not_triggered(mock_alert_config_with_aggregate, valid_device_ids):
    """Test average alert is NOT triggered when exactly at threshold (gt condition)"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config_with_aggregate, valid_device_ids)
    fake_snapshot = {
        "AIn02": 40.0,
        "AIn03": 40.0,
        # Average = 40.0 == 40.0 threshold (not > 40.0)
    }

    # Act
    results = evaluator.evaluate("ADAM-4117_12", fake_snapshot)

    # Assert
    avg_alerts = [r for r in results if r[0] == "AVG_TEMP_HIGH"]
    assert len(avg_alerts) == 0


def test_when_single_source_alert_then_display_without_aggregate_type(mock_alert_config, valid_device_ids):
    """Test single source alert displays source name only (not 'threshold(source)')"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config, valid_device_ids)
    fake_snapshot = {"AIn01": 55.0}

    # Act
    results = evaluator.evaluate("SD400_3", fake_snapshot)

    # Assert
    assert len(results) == 1
    # Should display "AIn01=55.00" not "threshold(AIn01)=55.00"
    assert "AIn01=" in results[0][1]
    assert "threshold(AIn01)" not in results[0][1]


def test_when_aggregate_alert_then_display_with_aggregate_type(mock_alert_config_with_aggregate, valid_device_ids):
    """Test aggregate alert displays type and sources (e.g. 'average(AIn02, AIn03)')"""
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config_with_aggregate, valid_device_ids)
    fake_snapshot = {
        "AIn02": 41.0,
        "AIn03": 42.0,
    }

    # Act
    results = evaluator.evaluate("ADAM-4117_12", fake_snapshot)

    # Assert
    avg_alerts = [r for r in results if r[0] == "AVG_TEMP_HIGH"]
    assert len(avg_alerts) == 1
    # Should display "average(AIn02, AIn03)=41.50"
    assert "average(AIn02, AIn03)=" in avg_alerts[0][1]
