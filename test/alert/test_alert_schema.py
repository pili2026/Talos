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
            "device_name": "Test Device",  # 新增
            "sources": ["O2_PCT"],
            "type": "threshold",
            "condition": "lt",
            "threshold": 1.5,
            "severity": "CRITICAL",
            "message": "Oxygen level is too low",  # 新增
        }
    )

    assert alert.code == "TEST_ALERT"
    assert alert.device_name == "Test Device"
    assert alert.sources == ["O2_PCT"]
    assert alert.condition == ConditionOperator.LESS_THAN
    assert alert.threshold == 1.5
    assert alert.type == ConditionType.THRESHOLD
    assert alert.message == "Oxygen level is too low"


def test_when_threshold_alert_missing_device_name_then_validation_error():
    """Test validation error when threshold alert missing device_name"""
    with pytest.raises(ValidationError) as exc_info:
        ThresholdAlertConfig.model_validate(
            {
                "code": "TEST",
                "name": "Test",
                "sources": ["O2_PCT"],
                "type": "threshold",
                "condition": "lt",
                "threshold": 1.5,
                "message": "Test message",
                # Missing device_name
            }
        )
    assert "device_name" in str(exc_info.value)


def test_when_threshold_alert_missing_message_then_validation_error():
    """Test validation error when threshold alert missing message"""
    with pytest.raises(ValidationError) as exc_info:
        ThresholdAlertConfig.model_validate(
            {
                "code": "TEST",
                "name": "Test",
                "device_name": "Test Device",
                "sources": ["O2_PCT"],
                "type": "threshold",
                "condition": "lt",
                "threshold": 1.5,
                # Missing message
            }
        )
    assert "message" in str(exc_info.value)


def test_when_threshold_alert_missing_condition_then_validation_error():
    """Test validation error when threshold alert missing condition"""
    with pytest.raises(ValidationError) as exc_info:
        ThresholdAlertConfig.model_validate(
            {
                "code": "TEST",
                "name": "Test",
                "device_name": "Test Device",
                "sources": ["O2_PCT"],
                "type": "threshold",
                "threshold": 1.5,
                "message": "Test message",
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
                "device_name": "Test Device",
                "sources": ["O2_PCT"],
                "type": "threshold",
                "condition": "gt",
                "message": "Test message",
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
                "device_name": "Test Device",
                "sources": [],  # Empty list
                "condition": "gt",
                "threshold": 50.0,
                "type": "threshold",
                "message": "Test message",
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
            "device_name": "Multi-Point Sensor",  # 新增
            "sources": ["AIn02", "AIn03"],
            "type": "average",
            "condition": "gt",
            "threshold": 40.0,
            "severity": "WARNING",
            "message": "Average temperature exceeds threshold",  # 新增
        }
    )

    assert alert.type == ConditionType.AVERAGE
    assert alert.device_name == "Multi-Point Sensor"
    assert len(alert.sources) == 2
    assert alert.condition == ConditionOperator.GREATER_THAN
    assert alert.message == "Average temperature exceeds threshold"


def test_when_average_with_single_source_then_validation_error():
    """Test validation error when average type has only one source"""
    with pytest.raises(ValidationError) as exc_info:
        AggregateAlertConfig.model_validate(
            {
                "code": "AVG_ALERT",
                "name": "Average Alert",
                "device_name": "Test Device",
                "sources": ["AIn01"],  # Only one source
                "condition": "gt",
                "threshold": 40.0,
                "type": "average",
                "message": "Test message",
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
                "device_name": "Test Device",
                "sources": ["AIn01"],
                "condition": "gt",
                "threshold": 100.0,
                "type": "sum",
                "message": "Test message",
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
                "device_name": "Test Device",
                "sources": ["AIn01"],
                "condition": "lt",
                "threshold": 10.0,
                "type": "min",
                "message": "Test message",
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
                "device_name": "Test Device",
                "sources": ["AIn01"],
                "condition": "gt",
                "threshold": 50.0,
                "type": "max",
                "message": "Test message",
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
                "device_name": "Test Device",  # 新增
                "sources": ["AIn01", "AIn02", "AIn03"],
                "condition": "gt",
                "threshold": 50.0,
                "type": agg_type,
                "message": f"{agg_type.title()} value exceeds threshold",  # 新增
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
            "device_name": "Main Blower",  # 新增
            "sources": ["RW_ON_OFF"],
            "type": "schedule_expected_state",
            "expected_state": 0,
            "severity": "WARNING",
            "message": "Blower is running outside scheduled hours",  # 新增
        }
    )

    assert alert.type == ConditionType.SCHEDULE_EXPECTED_STATE
    assert alert.device_name == "Main Blower"
    assert alert.expected_state == 0
    assert alert.use_work_hours is True  # Default
    assert alert.message == "Blower is running outside scheduled hours"


def test_when_schedule_alert_with_string_off_then_normalized_to_zero():
    """Test schedule alert with 'off' string is normalized to 0"""
    alert = ScheduleExpectedStateAlertConfig.model_validate(
        {
            "code": "BLOWER_AFTER_HOURS",
            "name": "Blower Running After Hours",
            "device_name": "Main Blower",
            "sources": ["RW_ON_OFF"],
            "type": "schedule_expected_state",
            "expected_state": "off",
            "message": "Test message",
        }
    )

    assert alert.expected_state == 0


def test_when_schedule_alert_with_string_on_then_normalized_to_one():
    """Test schedule alert with 'on' string is normalized to 1"""
    alert = ScheduleExpectedStateAlertConfig.model_validate(
        {
            "code": "COOLING_24_7",
            "name": "Cooling Must Run 24/7",
            "device_name": "Cooling System",
            "sources": ["RW_ON_OFF"],
            "type": "schedule_expected_state",
            "expected_state": "on",
            "message": "Test message",
        }
    )

    assert alert.expected_state == 1


def test_when_schedule_alert_with_uppercase_off_then_normalized_to_zero():
    """Test schedule alert with 'OFF' string is normalized to 0"""
    alert = ScheduleExpectedStateAlertConfig.model_validate(
        {
            "code": "TEST",
            "name": "Test",
            "device_name": "Test Device",
            "sources": ["RW_ON_OFF"],
            "type": "schedule_expected_state",
            "expected_state": "OFF",
            "message": "Test message",
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
                "device_name": "Test Device",
                "sources": ["RW_ON_OFF"],
                "type": "schedule_expected_state",
                "expected_state": "invalid",
                "message": "Test message",
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
                "device_name": "Test Device",
                "sources": ["RW_ON_OFF"],
                "type": "schedule_expected_state",
                "expected_state": 2,  # Not 0 or 1
                "message": "Test message",
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
                "device_name": "Test Device",
                "sources": ["RW_ON_OFF", "RW_CURRENT"],  # 2 sources
                "type": "schedule_expected_state",
                "expected_state": 0,
                "message": "Test message",
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
                "device_name": "Test Device",
                "sources": ["RW_ON_OFF"],
                "type": "schedule_expected_state",
                "message": "Test message",
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
            "device_name": "Test Device",
            "sources": ["RW_ON_OFF"],
            "type": "schedule_expected_state",
            "expected_state": 0,
            "use_work_hours": False,
            "message": "Test message",
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
                "device_name": "Test Device",
                "sources": [],  # Empty
                "type": "schedule_expected_state",
                "expected_state": 0,
                "message": "Test message",
            }
        )
    assert "sources must have at least one element" in str(exc_info.value)


def test_when_schedule_alert_with_message_then_stored():
    """Test schedule alert message field is stored correctly"""
    alert = ScheduleExpectedStateAlertConfig.model_validate(
        {
            "code": "TEST",
            "name": "Test",
            "device_name": "Test Device",
            "sources": ["RW_ON_OFF"],
            "type": "schedule_expected_state",
            "expected_state": 0,
            "message": "Custom detailed message",
        }
    )

    assert alert.message == "Custom detailed message"


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
                "device_name": "Test Device",
                "sources": ["AIn01"],
                "condition": "gt",
                "threshold": 50.0,
                "severity": severity,
                "message": f"Test {severity} message",
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
                "device_name": "Test Device",
                "sources": ["AIn01"],
                "condition": op,
                "threshold": 50.0,
                "message": f"Test {op} message",
            }
        )

        assert alert.condition == ConditionOperator(op)


def test_when_all_required_fields_present_then_threshold_alert_valid():
    """Test threshold alert requires all mandatory fields"""
    alert = ThresholdAlertConfig.model_validate(
        {
            "code": "COMPLETE_ALERT",
            "name": "Complete Alert",
            "device_name": "Complete Device",
            "sources": ["AIn01"],
            "condition": "gt",
            "threshold": 50.0,
            "severity": "WARNING",
            "type": "threshold",
            "message": "Complete alert message",
        }
    )

    assert alert.code == "COMPLETE_ALERT"
    assert alert.name == "Complete Alert"
    assert alert.device_name == "Complete Device"
    assert alert.message == "Complete alert message"


def test_when_all_required_fields_present_then_aggregate_alert_valid():
    """Test aggregate alert requires all mandatory fields"""
    alert = AggregateAlertConfig.model_validate(
        {
            "code": "COMPLETE_AGG",
            "name": "Complete Aggregate",
            "device_name": "Aggregate Device",
            "sources": ["AIn01", "AIn02"],
            "condition": "gt",
            "threshold": 50.0,
            "severity": "CRITICAL",
            "type": "average",
            "message": "Complete aggregate message",
        }
    )

    assert alert.code == "COMPLETE_AGG"
    assert alert.name == "Complete Aggregate"
    assert alert.device_name == "Aggregate Device"
    assert alert.message == "Complete aggregate message"


def test_when_all_required_fields_present_then_schedule_alert_valid():
    """Test schedule alert requires all mandatory fields"""
    alert = ScheduleExpectedStateAlertConfig.model_validate(
        {
            "code": "COMPLETE_SCHEDULE",
            "name": "Complete Schedule",
            "device_name": "Schedule Device",
            "sources": ["RW_ON_OFF"],
            "expected_state": 0,
            "severity": "WARNING",
            "type": "schedule_expected_state",
            "message": "Complete schedule message",
        }
    )

    assert alert.code == "COMPLETE_SCHEDULE"
    assert alert.name == "Complete Schedule"
    assert alert.device_name == "Schedule Device"
    assert alert.message == "Complete schedule message"
