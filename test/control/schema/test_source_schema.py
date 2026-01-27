import pytest
from pydantic import ValidationError

from core.model.enum.condition_enum import AggregationType
from core.schema.control_condition_source_schema import Source


class TestSourceValidation:
    """Test Source schema validation"""

    def test_valid_single_pin(self):
        """Valid source with single pin"""
        source = Source(device="ADAM-4117", slave_id="12", pins=["AIn01"])
        assert source.device == "ADAM-4117"
        assert source.slave_id == "12"
        assert source.pins == ["AIn01"]
        assert source.aggregation is None
        assert source.get_effective_aggregation() is None

    def test_valid_multiple_pins_with_aggregation(self):
        """Valid source with multiple pins and aggregation"""
        source = Source(
            device="ADAM-4117", slave_id="12", pins=["AIn01", "AIn02", "AIn03"], aggregation=AggregationType.AVERAGE
        )
        assert source.pins == ["AIn01", "AIn02", "AIn03"]
        assert source.aggregation == AggregationType.AVERAGE
        assert source.get_effective_aggregation() == AggregationType.AVERAGE

    def test_multiple_pins_default_aggregation(self):
        """Multiple pins without aggregation defaults to AVERAGE"""
        source = Source(device="ADAM-4117", slave_id="12", pins=["AIn01", "AIn02"])
        assert source.aggregation is None
        assert source.get_effective_aggregation() == AggregationType.AVERAGE

    def test_aggregation_from_yaml_string(self):
        """Aggregation can be specified as string in YAML (auto-converted to enum)"""
        source = Source(
            device="ADAM-4117", slave_id="12", pins=["AIn01", "AIn02"], aggregation="sum"  # ← String input (from YAML)
        )
        assert source.aggregation == AggregationType.SUM
        assert isinstance(source.aggregation, AggregationType)

    def test_empty_device_rejected(self):
        """Empty device name should be rejected"""
        with pytest.raises(ValidationError) as exc_info:
            Source(device="", slave_id="12", pins=["AIn01"])

        assert "device cannot be empty" in str(exc_info.value)

    def test_empty_slave_id_rejected(self):
        """Empty slave_id should be rejected"""
        with pytest.raises(ValidationError) as exc_info:
            Source(device="ADAM-4117", slave_id="", pins=["AIn01"])

        assert "slave_id cannot be empty" in str(exc_info.value)

    def test_empty_pins_rejected(self):
        """Empty pins list should be rejected"""
        with pytest.raises(ValidationError) as exc_info:
            Source(device="ADAM-4117", slave_id="12", pins=[])

        assert "pins list cannot be empty" in str(exc_info.value)

    def test_duplicate_pins_rejected(self):
        """Duplicate pins should be rejected"""
        with pytest.raises(ValidationError) as exc_info:
            Source(device="ADAM-4117", slave_id="12", pins=["AIn01", "AIn02", "AIn01"])

        assert "duplicates" in str(exc_info.value).lower()

    def test_invalid_aggregation_rejected(self):
        """Invalid aggregation method should be rejected"""
        with pytest.raises(ValidationError):
            Source(device="ADAM-4117", slave_id="12", pins=["AIn01", "AIn02"], aggregation="invalid_method")

    def test_str_representation(self):
        """Test string representation"""
        source = Source(device="ADAM-4117", slave_id="12", pins=["AIn01", "AIn02"], aggregation=AggregationType.AVERAGE)
        assert str(source) == "ADAM-4117_12:[AIn01,AIn02](average)"

    def test_str_representation_single_pin(self):
        """Test string representation for single pin (no aggregation)"""
        source = Source(device="TECO_VFD", slave_id="1", pins=["HZ"])
        assert str(source) == "TECO_VFD_1:HZ"


class TestSourceAggregationMethods:
    """Test all aggregation methods"""

    @pytest.mark.parametrize(
        "method",
        [
            AggregationType.AVERAGE,
            AggregationType.SUM,
            AggregationType.MIN,
            AggregationType.MAX,
            AggregationType.FIRST,
            AggregationType.LAST,
        ],
    )
    def test_all_aggregation_methods(self, method):
        """Test all valid aggregation methods"""
        source = Source(device="ADAM-4117", slave_id="12", pins=["AIn01", "AIn02"], aggregation=method)
        assert source.aggregation == method
        assert source.get_effective_aggregation() == method

    @pytest.mark.parametrize(
        "method_str,expected_enum",
        [
            ("average", AggregationType.AVERAGE),
            ("sum", AggregationType.SUM),
            ("min", AggregationType.MIN),
            ("max", AggregationType.MAX),
            ("first", AggregationType.FIRST),
            ("last", AggregationType.LAST),
        ],
    )
    def test_string_to_enum_conversion(self, method_str, expected_enum):
        """Test automatic conversion from string to enum (YAML support)"""
        source = Source(device="ADAM-4117", slave_id="12", pins=["AIn01", "AIn02"], aggregation=method_str)
        assert source.aggregation == expected_enum  # ← Enum


class TestSourceEdgeCases:
    """Test edge cases and error handling"""

    def test_whitespace_trimming(self):
        """Test that whitespace is properly trimmed"""
        source = Source(device="  ADAM-4117  ", slave_id="  12  ", pins=["  AIn01  ", "  AIn02  "])
        assert source.device == "ADAM-4117"
        assert source.slave_id == "12"
        assert source.pins == ["AIn01", "AIn02"]

    def test_extra_fields_rejected(self):
        """Test that unknown fields are rejected (extra='forbid')"""
        with pytest.raises(ValidationError) as exc_info:
            Source(device="ADAM-4117", slave_id="12", pins=["AIn01"], unknown_field="value")

        errors = exc_info.value.errors()
        assert errors[0]["loc"] == ("unknown_field",)
        assert errors[0]["type"] == "extra_forbidden"

    def test_slave_id_numeric_to_string_conversion(self):
        """Test that numeric slave_id is converted to string"""
        source = Source(device="ADAM-4117", slave_id=12, pins=["AIn01"])
        assert source.slave_id == "12"
        assert isinstance(source.slave_id, str)
