import pytest
from pydantic import ValidationError

from core.model.enum.alert_enum import AlertSeverity
from core.model.enum.condition_enum import ConditionOperator, ConditionType
from core.schema.alert_schema import AggregateAlertConfig, ScheduleExpectedStateAlertConfig, ThresholdAlertConfig

# ============================================================
# Threshold Alert Schema Tests
# ============================================================


def test_when_valid_threshold_alert_then_validation_succeeds():
    """Test threshold alert with valid configuration"""
    alert = ThresholdAlertConfig.model_validate(
        {
            "code": "TEST_ALERT",
            "name": "Test Alert",
            "sources": ["O2_PCT"],
            "type": "threshold",
            "condition": "lt",
            "threshold": 1.5,
            "severity": "CRITICAL",
        }
    )

    assert alert.code == "TEST_ALERT"
    assert alert.sources == ["O2_PCT"]
    assert alert.condition == ConditionOperator.LESS_THAN
    assert alert.threshold == 1.5
    assert alert.type == ConditionType.THRESHOLD


def test_when_threshold_alert_missing_condition_then_validation_error():
    """Test validation error when threshold alert missing condition"""
    with pytest.raises(ValidationError) as exc_info:
        ThresholdAlertConfig.model_validate(
            {
                "code": "TEST",
                "name": "Test",
                "sources": ["O2_PCT"],
                "type": "threshold",
                "threshold": 1.5,
                # Missing condition
            }
        )
    assert "condition" in str(exc_info.value)


def test_when_threshold_alert_missing_threshold_then_validation_error():
    """Test validation error when threshold alert missing threshold"""
    with pytest.raises(ValidationError) as exc_info:
        ThresholdAlertConfig.model_validate(
            {
                "code": "TEST",
                "name": "Test",
                "sources": ["O2_PCT"],
                "type": "threshold",
                "condition": "gt",
                # Missing threshold
            }
        )
    assert "threshold" in str(exc_info.value)


def test_when_threshold_alert_empty_sources_then_validation_error():
    """Test validation error when sources list is empty"""
    with pytest.raises(ValidationError) as exc_info:
        ThresholdAlertConfig.model_validate(
            {
                "code": "TEST_ALERT",
                "name": "Test Alert",
                "sources": [],  # Empty list
                "condition": "gt",
                "threshold": 50.0,
                "type": "threshold",
            }
        )
    assert "sources must have at least one element" in str(exc_info.value)


# ============================================================
# Aggregate Alert Schema Tests
# ============================================================


def test_when_valid_average_alert_then_validation_succeeds():
    """Test average alert with valid configuration"""
    alert = AggregateAlertConfig.model_validate(
        {
            "code": "AVG_TEMP",
            "name": "Average Temperature",
            "sources": ["AIn02", "AIn03"],
            "type": "average",
            "condition": "gt",
            "threshold": 40.0,
            "severity": "WARNING",
        }
    )

    assert alert.type == ConditionType.AVERAGE
    assert len(alert.sources) == 2
    assert alert.condition == ConditionOperator.GREATER_THAN


def test_when_average_with_single_source_then_validation_error():
    """Test validation error when average type has only one source"""
    with pytest.raises(ValidationError) as exc_info:
        AggregateAlertConfig.model_validate(
            {
                "code": "AVG_ALERT",
                "name": "Average Alert",
                "sources": ["AIn01"],  # Only one source
                "condition": "gt",
                "threshold": 40.0,
                "type": "average",
            }
        )
    assert "at least 2 sources" in str(exc_info.value)


def test_when_sum_with_single_source_then_validation_error():
    """Test validation error when sum type has only one source"""
    with pytest.raises(ValidationError) as exc_info:
        AggregateAlertConfig.model_validate(
            {
                "code": "SUM_ALERT",
                "name": "Sum Alert",
                "sources": ["AIn01"],
                "condition": "gt",
                "threshold": 100.0,
                "type": "sum",
            }
        )
    assert "at least 2 sources" in str(exc_info.value)


def test_when_min_with_single_source_then_validation_error():
    """Test validation error when min type has only one source"""
    with pytest.raises(ValidationError) as exc_info:
        AggregateAlertConfig.model_validate(
            {
                "code": "MIN_ALERT",
                "name": "Min Alert",
                "sources": ["AIn01"],
                "condition": "lt",
                "threshold": 10.0,
                "type": "min",
            }
        )
    assert "at least 2 sources" in str(exc_info.value)


def test_when_max_with_single_source_then_validation_error():
    """Test validation error when max type has only one source"""
    with pytest.raises(ValidationError) as exc_info:
        AggregateAlertConfig.model_validate(
            {
                "code": "MAX_ALERT",
                "name": "Max Alert",
                "sources": ["AIn01"],
                "condition": "gt",
                "threshold": 50.0,
                "type": "max",
            }
        )
    assert "at least 2 sources" in str(exc_info.value)


def test_when_all_aggregate_types_with_multiple_sources_then_validation_succeeds():
    """Test all aggregate types are valid with multiple sources"""
    types = ["average", "sum", "min", "max"]

    for agg_type in types:
        alert = AggregateAlertConfig.model_validate(
            {
                "code": f"{agg_type.upper()}_ALERT",
                "name": f"{agg_type.title()} Alert",
                "sources": ["AIn01", "AIn02", "AIn03"],
                "condition": "gt",
                "threshold": 50.0,
                "type": agg_type,
            }
        )

        assert alert.type == ConditionType(agg_type)
        assert len(alert.sources) == 3


# ============================================================
# Schedule Expected State Alert Schema Tests
# ============================================================


def test_when_valid_schedule_alert_with_int_state_then_validation_succeeds():
    """Test schedule alert with integer expected_state"""
    alert = ScheduleExpectedStateAlertConfig.model_validate(
        {
            "code": "BLOWER_AFTER_HOURS",
            "name": "Blower Running After Hours",
            "sources": ["RW_ON_OFF"],
            "type": "schedule_expected_state",
            "expected_state": 0,
            "severity": "WARNING",
        }
    )

    assert alert.type == ConditionType.SCHEDULE_EXPECTED_STATE
    assert alert.expected_state == 0
    assert alert.use_work_hours is True  # Default


def test_when_schedule_alert_with_string_off_then_normalized_to_zero():
    """Test schedule alert with 'off' string is normalized to 0"""
    alert = ScheduleExpectedStateAlertConfig.model_validate(
        {
            "code": "BLOWER_AFTER_HOURS",
            "name": "Blower Running After Hours",
            "sources": ["RW_ON_OFF"],
            "type": "schedule_expected_state",
            "expected_state": "off",
        }
    )

    assert alert.expected_state == 0


def test_when_schedule_alert_with_string_on_then_normalized_to_one():
    """Test schedule alert with 'on' string is normalized to 1"""
    alert = ScheduleExpectedStateAlertConfig.model_validate(
        {
            "code": "COOLING_24_7",
            "name": "Cooling Must Run 24/7",
            "sources": ["RW_ON_OFF"],
            "type": "schedule_expected_state",
            "expected_state": "on",
        }
    )

    assert alert.expected_state == 1


def test_when_schedule_alert_with_uppercase_off_then_normalized_to_zero():
    """Test schedule alert with 'OFF' string is normalized to 0"""
    alert = ScheduleExpectedStateAlertConfig.model_validate(
        {
            "code": "TEST",
            "name": "Test",
            "sources": ["RW_ON_OFF"],
            "type": "schedule_expected_state",
            "expected_state": "OFF",
        }
    )

    assert alert.expected_state == 0


def test_when_schedule_alert_with_invalid_string_then_validation_error():
    """Test validation error when expected_state is invalid string"""
    with pytest.raises(ValidationError) as exc_info:
        ScheduleExpectedStateAlertConfig.model_validate(
            {
                "code": "TEST",
                "name": "Test",
                "sources": ["RW_ON_OFF"],
                "type": "schedule_expected_state",
                "expected_state": "invalid",
            }
        )
    assert "must be 0/1 or 'on'/'off'" in str(exc_info.value)


def test_when_schedule_alert_with_invalid_numeric_state_then_validation_error():
    """Test validation error when expected_state is invalid number"""
    with pytest.raises(ValidationError) as exc_info:
        ScheduleExpectedStateAlertConfig.model_validate(
            {
                "code": "TEST",
                "name": "Test",
                "sources": ["RW_ON_OFF"],
                "type": "schedule_expected_state",
                "expected_state": 2,  # Not 0 or 1
            }
        )
    assert "must be 0 or 1" in str(exc_info.value)


def test_when_schedule_alert_with_multiple_sources_then_validation_error():
    """Test validation error when schedule alert has multiple sources"""
    with pytest.raises(ValidationError) as exc_info:
        ScheduleExpectedStateAlertConfig.model_validate(
            {
                "code": "TEST",
                "name": "Test",
                "sources": ["RW_ON_OFF", "RW_CURRENT"],  # 2 sources
                "type": "schedule_expected_state",
                "expected_state": 0,
            }
        )
    assert "exactly 1 source" in str(exc_info.value)


def test_when_schedule_alert_missing_expected_state_then_validation_error():
    """Test validation error when schedule alert missing expected_state"""
    with pytest.raises(ValidationError) as exc_info:
        ScheduleExpectedStateAlertConfig.model_validate(
            {
                "code": "TEST",
                "name": "Test",
                "sources": ["RW_ON_OFF"],
                "type": "schedule_expected_state",
                # Missing expected_state
            }
        )
    assert "expected_state" in str(exc_info.value)


def test_when_schedule_alert_with_custom_use_work_hours_then_respected():
    """Test schedule alert with custom use_work_hours setting"""
    alert = ScheduleExpectedStateAlertConfig.model_validate(
        {
            "code": "TEST",
            "name": "Test",
            "sources": ["RW_ON_OFF"],
            "type": "schedule_expected_state",
            "expected_state": 0,
            "use_work_hours": False,
        }
    )

    assert alert.use_work_hours is False


def test_when_schedule_alert_with_empty_sources_then_validation_error():
    """Test validation error when schedule alert has empty sources"""
    with pytest.raises(ValidationError) as exc_info:
        ScheduleExpectedStateAlertConfig.model_validate(
            {
                "code": "TEST",
                "name": "Test",
                "sources": [],  # Empty
                "type": "schedule_expected_state",
                "expected_state": 0,
            }
        )
    assert "sources must have at least one element" in str(exc_info.value)


def test_when_schedule_alert_with_optional_message_then_stored():
    """Test schedule alert with optional message field"""
    alert = ScheduleExpectedStateAlertConfig.model_validate(
        {
            "code": "TEST",
            "name": "Test",
            "sources": ["RW_ON_OFF"],
            "type": "schedule_expected_state",
            "expected_state": 0,
            "message": "Custom message",
        }
    )

    assert alert.message == "Custom message"


# ============================================================
# Common Tests (apply to all alert types)
# ============================================================


def test_when_valid_severity_levels_then_accepted():
    """Test all valid severity levels are accepted"""
    severities = ["CRITICAL", "ERROR", "WARNING", "INFO"]

    for severity in severities:
        alert = ThresholdAlertConfig.model_validate(
            {
                "code": f"TEST_{severity}",
                "name": "Test Alert",
                "sources": ["AIn01"],
                "condition": "gt",
                "threshold": 50.0,
                "severity": severity,
            }
        )

        assert alert.severity == AlertSeverity(severity)


def test_when_valid_condition_operators_then_accepted():
    """Test all valid condition operators are accepted"""
    operators = ["gt", "lt", "eq", "gte", "lte", "neq"]

    for op in operators:
        alert = ThresholdAlertConfig.model_validate(
            {
                "code": f"TEST_{op.upper()}",
                "name": "Test Alert",
                "sources": ["AIn01"],
                "condition": op,
                "threshold": 50.0,
            }
        )

        assert alert.condition == ConditionOperator(op)
