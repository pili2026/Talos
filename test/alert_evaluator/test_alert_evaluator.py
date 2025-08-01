from evaluator.alert_evaluator import AlertEvaluator


def test_when_device_has_custom_alert_then_trigger_alert_if_condition_met(mock_alert_config, valid_device_ids):
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config, valid_device_ids)
    fakse_snapshot = {"AIn02": 3.0}

    # Act
    results = evaluator.evaluate("SD400_7", fakse_snapshot)

    # Assert
    assert len(results) == 1
    assert results[0][0] == "AIN02_LOW"
    assert "AIn02" in results[0][1]


def test_when_device_uses_default_alerts_then_fallback_and_trigger_if_condition_met(
    mock_alert_config, valid_device_ids
):
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config, valid_device_ids)
    fakse_snapshot = {"AIn01": 51.0}

    # Act
    results = evaluator.evaluate("SD400_3", fakse_snapshot)

    # Assert
    assert len(results) == 1
    assert results[0][0] == "AIN01_HIGH"
    assert "AIn01" in results[0][1]


def test_when_device_has_no_alerts_then_return_empty(mock_alert_config, valid_device_ids):
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config, valid_device_ids)
    fakse_snapshot = {"AIn01": 60.0}

    # Act
    results = evaluator.evaluate("SD400_9", fakse_snapshot)

    # Assert
    assert len(results) == 0


def test_when_snapshot_missing_alert_source_then_log_warning_and_skip(mock_alert_config, caplog, valid_device_ids):
    # Arrange
    evaluator = AlertEvaluator(mock_alert_config, valid_device_ids)
    fakse_snapshot = {"AIn03": 60.0}

    # Act
    with caplog.at_level("WARNING"):
        results = evaluator.evaluate("SD400_3", fakse_snapshot)

    # Assert
    assert len(results) == 0
    assert any("Pin 'AIn01' not in snapshot" in msg for msg in caplog.messages)


def test_when_alert_config_target_device_not_found_then_skip(mock_alert_config_with_unknown_device, caplog):
    # Arrange
    fakse_valid_device_ids = {"SD400_3"}

    # Act
    with caplog.at_level("WARNING", logger="AlertEvaluator"):
        _ = AlertEvaluator(mock_alert_config_with_unknown_device, fakse_valid_device_ids)

    # Assert
    assert "SD400_999" not in _.device_alert_dict.get("SD400", {})
    assert any("[SKIP] Unknown device in config: SD400_999" in msg for msg in caplog.messages)
