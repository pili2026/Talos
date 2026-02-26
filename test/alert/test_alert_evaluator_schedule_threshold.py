from datetime import time
from unittest.mock import patch

from core.evaluator.alert_evaluator import AlertEvaluator
from core.model.enum.alert_enum import AlertSeverity
from core.model.enum.alert_state_enum import AlertState

DEVICE_ID = "ADTEK_CPM10_1"
VALID_DEVICE_IDS = {DEVICE_ID}


# ============================================================
# Inside active_hours Tests
# ============================================================


def test_when_inside_active_hours_and_exceeds_threshold_then_trigger(
    mock_alert_config_with_schedule_threshold,
):
    """Inside active_hours, value exceeds threshold → triggered"""
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule_threshold,
        valid_device_ids=VALID_DEVICE_IDS,
    )

    with patch("core.evaluator.alert_evaluator.datetime") as mock_dt:
        mock_dt.now.return_value.time.return_value = time(22, 0)  # 22:00 inside 20:00~07:00
        results = evaluator.evaluate(DEVICE_ID, {"Kw": 15.0})

    assert len(results) == 1
    result = results[0]
    assert result.alert_code == "NIGHT_KW_HIGH"
    assert result.notification_type == AlertState.TRIGGERED.name
    assert result.current_value == 15.0
    assert result.severity == AlertSeverity.WARNING


def test_when_inside_active_hours_and_below_threshold_then_no_alert(
    mock_alert_config_with_schedule_threshold,
):
    """Inside active_hours, value below threshold → no alert"""
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule_threshold,
        valid_device_ids=VALID_DEVICE_IDS,
    )

    with patch("core.evaluator.alert_evaluator.datetime") as mock_dt:
        mock_dt.now.return_value.time.return_value = time(22, 0)
        results = evaluator.evaluate(DEVICE_ID, {"Kw": 8.0})

    assert len(results) == 0


# ============================================================
# Outside active_hours Tests
# ============================================================


def test_when_outside_active_hours_and_exceeds_threshold_then_suppressed(
    mock_alert_config_with_schedule_threshold,
):
    """Outside active_hours, value exceeds threshold → suppressed"""
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule_threshold,
        valid_device_ids=VALID_DEVICE_IDS,
    )

    with patch("core.evaluator.alert_evaluator.datetime") as mock_dt:
        mock_dt.now.return_value.time.return_value = time(10, 0)  # 10:00 outside 20:00~07:00
        results = evaluator.evaluate(DEVICE_ID, {"Kw": 15.0})

    assert len(results) == 0


# ============================================================
# Overnight Boundary Tests
# ============================================================


def test_when_at_active_hours_start_boundary_then_trigger(
    mock_alert_config_with_schedule_threshold,
):
    """Exactly at active_hours start (20:00) → inside, trigger"""
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule_threshold,
        valid_device_ids=VALID_DEVICE_IDS,
    )

    with patch("core.evaluator.alert_evaluator.datetime") as mock_dt:
        mock_dt.now.return_value.time.return_value = time(20, 0)
        results = evaluator.evaluate(DEVICE_ID, {"Kw": 15.0})

    assert len(results) == 1


def test_when_at_active_hours_end_boundary_then_trigger(
    mock_alert_config_with_schedule_threshold,
):
    """Exactly at active_hours end (07:00) → inside, trigger"""
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule_threshold,
        valid_device_ids=VALID_DEVICE_IDS,
    )

    with patch("core.evaluator.alert_evaluator.datetime") as mock_dt:
        mock_dt.now.return_value.time.return_value = time(7, 0)
        results = evaluator.evaluate(DEVICE_ID, {"Kw": 15.0})

    assert len(results) == 1


def test_when_just_past_active_hours_end_then_suppressed(
    mock_alert_config_with_schedule_threshold,
):
    """Just past active_hours end (07:01) → outside, suppressed"""
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule_threshold,
        valid_device_ids=VALID_DEVICE_IDS,
    )

    with patch("core.evaluator.alert_evaluator.datetime") as mock_dt:
        mock_dt.now.return_value.time.return_value = time(7, 1)
        results = evaluator.evaluate(DEVICE_ID, {"Kw": 15.0})

    assert len(results) == 0


def test_when_midnight_in_overnight_interval_then_trigger(
    mock_alert_config_with_schedule_threshold,
):
    """Midnight (00:00) is inside overnight interval 20:00~07:00"""
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule_threshold,
        valid_device_ids=VALID_DEVICE_IDS,
    )

    with patch("core.evaluator.alert_evaluator.datetime") as mock_dt:
        mock_dt.now.return_value.time.return_value = time(0, 0)
        results = evaluator.evaluate(DEVICE_ID, {"Kw": 15.0})

    assert len(results) == 1


# ============================================================
# Missing Source Tests
# ============================================================


def test_when_source_missing_then_skip_evaluation(
    mock_alert_config_with_schedule_threshold,
):
    """Missing source in snapshot → return None, no alert"""
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule_threshold,
        valid_device_ids=VALID_DEVICE_IDS,
    )

    with patch("core.evaluator.alert_evaluator.datetime") as mock_dt:
        mock_dt.now.return_value.time.return_value = time(22, 0)
        results = evaluator.evaluate(DEVICE_ID, {})  # Empty snapshot

    assert len(results) == 0


# ============================================================
# State Transition Tests
# ============================================================


def test_when_alert_triggered_twice_inside_active_hours_then_only_first_notifies(
    mock_alert_config_with_schedule_threshold,
):
    """Continuous violation inside active_hours → only first cycle notifies"""
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule_threshold,
        valid_device_ids=VALID_DEVICE_IDS,
    )

    with patch("core.evaluator.alert_evaluator.datetime") as mock_dt:
        mock_dt.now.return_value.time.return_value = time(22, 0)

        results_first = evaluator.evaluate(DEVICE_ID, {"Kw": 15.0})
        assert len(results_first) == 1
        assert results_first[0].notification_type == AlertState.TRIGGERED.name

        results_second = evaluator.evaluate(DEVICE_ID, {"Kw": 15.0})
        assert len(results_second) == 0


def test_when_alert_resolves_inside_active_hours_then_resolved_notification(
    mock_alert_config_with_schedule_threshold,
):
    """Value drops below threshold inside active_hours → RESOLVED"""
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule_threshold,
        valid_device_ids=VALID_DEVICE_IDS,
    )

    with patch("core.evaluator.alert_evaluator.datetime") as mock_dt:
        mock_dt.now.return_value.time.return_value = time(22, 0)

        evaluator.evaluate(DEVICE_ID, {"Kw": 15.0})  # Trigger

        results_resolved = evaluator.evaluate(DEVICE_ID, {"Kw": 8.0})
        assert len(results_resolved) == 1
        assert results_resolved[0].notification_type == AlertState.RESOLVED.name


def test_when_outside_active_hours_then_state_not_changed(
    mock_alert_config_with_schedule_threshold,
):
    """Suppressed evaluations (outside active_hours) should not affect state machine"""
    evaluator = AlertEvaluator(
        alert_config=mock_alert_config_with_schedule_threshold,
        valid_device_ids=VALID_DEVICE_IDS,
    )

    with patch("core.evaluator.alert_evaluator.datetime") as mock_dt:
        # Outside active_hours - should be suppressed, state stays NORMAL
        mock_dt.now.return_value.time.return_value = time(10, 0)
        evaluator.evaluate(DEVICE_ID, {"Kw": 15.0})

        state = evaluator.state_manager.get_state(DEVICE_ID, "NIGHT_KW_HIGH")
        assert state == AlertState.NORMAL
