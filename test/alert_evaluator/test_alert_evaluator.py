from alert_evaluator import AlertEvaluator


def test_when_device_has_custom_alert_then_trigger_alert_if_condition_met(alert_config, valid_device_ids):
    evaluator = AlertEvaluator(alert_config, valid_device_ids)
    snapshot = {"AIn02": 3.0}
    results = evaluator.evaluate("SD400_7", snapshot)

    assert len(results) == 1
    assert results[0][0] == "AIN02_LOW"
    assert "AIn02" in results[0][1]


def test_when_device_uses_default_alerts_then_fallback_and_trigger_if_condition_met(alert_config, valid_device_ids):
    evaluator = AlertEvaluator(alert_config, valid_device_ids)
    snapshot = {"AIn01": 51.0}
    results = evaluator.evaluate("SD400_3", snapshot)

    assert len(results) == 1
    assert results[0][0] == "AIN01_HIGH"
    assert "AIn01" in results[0][1]


def test_when_device_has_no_alerts_then_return_empty(alert_config, valid_device_ids):
    evaluator = AlertEvaluator(alert_config, valid_device_ids)
    snapshot = {"AIn01": 60.0}
    results = evaluator.evaluate("SD400_9", snapshot)

    assert len(results) == 0


def test_when_snapshot_missing_alert_source_then_log_warning_and_skip(alert_config, caplog, valid_device_ids):
    evaluator = AlertEvaluator(alert_config, valid_device_ids)
    snapshot = {"AIn03": 60.0}

    with caplog.at_level("WARNING"):
        results = evaluator.evaluate("SD400_3", snapshot)

    assert len(results) == 0
    assert any("Pin 'AIn01' not in snapshot" in msg for msg in caplog.messages)


def test_when_alert_config_target_device_not_found_then_skip(alert_config_with_unknown_device, caplog):
    valid_device_ids = {"SD400_3"}
    with caplog.at_level("WARNING"):
        evaluator = AlertEvaluator(alert_config_with_unknown_device, valid_device_ids)

    assert "SD400_999" not in evaluator.device_alert_dict
    assert any("unknown device: SD400_999" in msg for msg in caplog.messages)
