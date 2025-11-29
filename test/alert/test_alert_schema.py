import pytest
from pydantic import ValidationError

from schema.alert_schema import AlertConditionModel

# ============================================================
# Schema Validation Tests
# ============================================================


def test_when_sources_empty_then_validation_error():
    """Test validation error when sources list is empty"""
    with pytest.raises(ValidationError) as exc_info:
        AlertConditionModel(
            name="Test Alert",
            code="TEST_ALERT",
            sources=[],  # Empty list
            condition="gt",
            threshold=50.0,
        )

    assert "sources must have at least one element" in str(exc_info.value)


def test_when_single_source_threshold_then_valid():
    """Test single source with threshold type is valid"""
    alert = AlertConditionModel(
        name="Test Alert",
        code="TEST_ALERT",
        sources=["AIn01"],
        condition="gt",
        threshold=50.0,
        type="threshold",
    )

    assert alert.sources == ["AIn01"]
    assert alert.type == "threshold"


def test_when_average_with_single_source_then_validation_error():
    """Test validation error when average type has only one source"""
    with pytest.raises(ValidationError) as exc_info:
        AlertConditionModel(
            name="Average Alert",
            code="AVG_ALERT",
            sources=["AIn01"],  # Only one source
            condition="gt",
            threshold=40.0,
            type="average",
        )

    assert "average requires at least 2 sources" in str(exc_info.value)


def test_when_average_with_multiple_sources_then_valid():
    """Test average type with multiple sources is valid"""
    alert = AlertConditionModel(
        name="Average Alert",
        code="AVG_ALERT",
        sources=["AIn01", "AIn02"],
        condition="gt",
        threshold=40.0,
        type="average",
    )

    assert alert.sources == ["AIn01", "AIn02"]
    assert alert.type == "average"


def test_when_sum_with_single_source_then_validation_error():
    """Test validation error when sum type has only one source"""
    with pytest.raises(ValidationError) as exc_info:
        AlertConditionModel(
            name="Sum Alert",
            code="SUM_ALERT",
            sources=["AIn01"],
            condition="gt",
            threshold=100.0,
            type="sum",
        )

    assert "sum requires at least 2 sources" in str(exc_info.value)


def test_when_min_with_single_source_then_validation_error():
    """Test validation error when min type has only one source"""
    with pytest.raises(ValidationError) as exc_info:
        AlertConditionModel(
            name="Min Alert",
            code="MIN_ALERT",
            sources=["AIn01"],
            condition="lt",
            threshold=10.0,
            type="min",
        )

    assert "min requires at least 2 sources" in str(exc_info.value)


def test_when_max_with_single_source_then_validation_error():
    """Test validation error when max type has only one source"""
    with pytest.raises(ValidationError) as exc_info:
        AlertConditionModel(
            name="Max Alert",
            code="MAX_ALERT",
            sources=["AIn01"],
            condition="gt",
            threshold=50.0,
            type="max",
        )

    assert "max requires at least 2 sources" in str(exc_info.value)


def test_when_all_aggregate_types_with_multiple_sources_then_valid():
    """Test all aggregate types are valid with multiple sources"""
    types = ["average", "sum", "min", "max"]

    for agg_type in types:
        alert = AlertConditionModel(
            name=f"{agg_type.title()} Alert",
            code=f"{agg_type.upper()}_ALERT",
            sources=["AIn01", "AIn02", "AIn03"],
            condition="gt",
            threshold=50.0,
            type=agg_type,
        )

        assert alert.type == agg_type
        assert len(alert.sources) == 3


def test_when_default_type_then_threshold():
    """Test default type is 'threshold'"""
    alert = AlertConditionModel(
        name="Test Alert",
        code="TEST_ALERT",
        sources=["AIn01"],
        condition="gt",
        threshold=50.0,
        # type not specified
    )

    assert alert.type == "threshold"


def test_when_optional_message_provided_then_stored():
    """Test optional message field is stored"""
    alert = AlertConditionModel(
        name="Test Alert",
        code="TEST_ALERT",
        sources=["AIn01"],
        condition="gt",
        threshold=50.0,
        message="Custom alert message",
    )

    assert alert.message == "Custom alert message"


def test_when_optional_message_not_provided_then_none():
    """Test optional message field defaults to None"""
    alert = AlertConditionModel(
        name="Test Alert",
        code="TEST_ALERT",
        sources=["AIn01"],
        condition="gt",
        threshold=50.0,
    )

    assert alert.message is None


def test_when_multiple_sources_different_order_then_preserves_order():
    """Test sources list preserves order"""
    alert = AlertConditionModel(
        name="Average Alert",
        code="AVG_ALERT",
        sources=["AIn03", "AIn01", "AIn02"],
        condition="gt",
        threshold=40.0,
        type="average",
    )

    assert alert.sources == ["AIn03", "AIn01", "AIn02"]


def test_when_valid_condition_operators_then_accepted():
    """Test all valid condition operators are accepted"""
    operators = ["gt", "lt", "eq", "gte", "lte", "neq"]

    for op in operators:
        alert = AlertConditionModel(
            name="Test Alert",
            code=f"TEST_{op.upper()}",
            sources=["AIn01"],
            condition=op,
            threshold=50.0,
        )

        assert alert.condition == op


def test_when_valid_severity_levels_then_accepted():
    """Test all valid severity levels are accepted"""
    severities = ["CRITICAL", "ERROR", "WARNING", "INFO"]

    for severity in severities:
        alert = AlertConditionModel(
            name="Test Alert",
            code=f"TEST_{severity}",
            sources=["AIn01"],
            condition="gt",
            threshold=50.0,
            severity=severity,
        )

        assert alert.severity == severity
