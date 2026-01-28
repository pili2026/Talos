import pytest
from pydantic import ValidationError

from core.model.control_execution import WrittenTarget


class TestWrittenTarget:
    """Test WrittenTarget model"""

    def test_when_create_with_valid_fields_then_success(self):
        """Test creating a valid WrittenTarget"""
        # Act
        written = WrittenTarget(value=50.0, priority=10, rule_code="TEMP_CTRL_01")

        # Assert
        assert written.value == 50.0
        assert written.priority == 10
        assert written.rule_code == "TEMP_CTRL_01"

    def test_when_assign_to_frozen_model_then_raise_validation_error(self):
        """Test that WrittenTarget is immutable"""
        # Act
        written = WrittenTarget(value=50.0, priority=10, rule_code="TEST")

        with pytest.raises(ValidationError) as exc_info:
            written.value = 60.0

        # Assert
        assert "frozen" in str(exc_info.value).lower() or "immutable" in str(exc_info.value).lower()

    def test_when_priority_is_negative_then_raise_validation_error(self):
        """Test that priority must be non-negative"""
        # Act
        with pytest.raises(ValidationError) as exc_info:
            WrittenTarget(value=50.0, priority=-1, rule_code="TEST")

        # Assert
        errs = exc_info.value.errors()
        assert errs[0]["loc"] == ("priority",)
        assert errs[0]["type"] in {"greater_than_equal"}
        assert "greater than or equal to 0" in errs[0]["msg"].lower()

    def test_when_rule_code_is_empty_then_raise_validation_error(self):
        """Test that rule_code cannot be empty"""
        # Act
        with pytest.raises(ValidationError) as exc_info:
            WrittenTarget(value=50.0, priority=10, rule_code="")

        # Assert
        errs = exc_info.value.errors()
        assert errs[0]["loc"] == ("rule_code",)
        assert errs[0]["type"] in {"string_too_short", "too_short"}
        assert "at least 1 character" in errs[0]["msg"].lower() or "too short" in errs[0]["msg"].lower()

    def test_when_rule_code_has_leading_or_trailing_whitespace_then_strip(self):
        """Test that rule_code whitespace is stripped"""
        # Act
        written = WrittenTarget(value=50.0, priority=10, rule_code="  TEMP_CTRL_01  ")

        # Assert
        assert written.rule_code == "TEMP_CTRL_01"

    def test_when_convert_to_str_then_return_expected_representation(self):
        """Test string representation"""
        # Act
        written = WrittenTarget(value=50.0, priority=10, rule_code="TEST")

        # Assert
        assert str(written) == "WrittenTarget(value=50.0, priority=10, rule=TEST)"

    def test_when_convert_to_repr_then_return_expected_representation(self):
        """Test repr representation"""
        # Act
        written = WrittenTarget(value=50.0, priority=10, rule_code="TEST")

        # Assert
        assert repr(written) == "WrittenTarget(value=50.0, priority=10, rule_code='TEST')"

    def test_when_value_is_int_then_accept_and_keep_int_type(self):
        """Test that value can be int"""
        # Act
        written = WrittenTarget(value=1, priority=10, rule_code="TEST")

        # Assert
        assert written.value == 1
        assert isinstance(written.value, int)

    def test_when_value_is_float_then_accept_and_keep_float_type(self):
        """Test that value can be float"""
        # Act
        written = WrittenTarget(value=50.5, priority=10, rule_code="TEST")

        # Assert
        assert written.value == 50.5
        assert isinstance(written.value, float)

    def test_when_priority_is_higher_then_return_true(self):
        """Test has_higher_priority_than method"""
        # Arrange
        written = WrittenTarget(value=50.0, priority=10, rule_code="TEST")

        # Act & Assert
        assert written.has_higher_priority_than(20) is True
        assert written.has_higher_priority_than(5) is False
        assert written.has_higher_priority_than(10) is False  # Equal priority

    def test_when_value_differs_then_conflicts(self):
        """Test conflicts_with method with default tolerance"""
        # Arrange
        written = WrittenTarget(value=50.0, priority=10, rule_code="TEST")

        # Act & Assert
        assert written.conflicts_with(60.0) is True
        assert written.conflicts_with(50.0) is False

    def test_when_float_value_within_tolerance_then_no_conflict(self):
        """Test that float values within tolerance don't conflict"""
        # Arrange
        written = WrittenTarget(value=50.0, priority=10, rule_code="TEST")

        # Act & Assert
        assert written.conflicts_with(50.05, tolerance=0.1) is False
        assert written.conflicts_with(49.95, tolerance=0.1) is False
        assert written.conflicts_with(50.0, tolerance=0.1) is False

    def test_when_float_value_beyond_tolerance_then_conflicts(self):
        """Test that float values beyond tolerance do conflict"""
        # Arrange
        written = WrittenTarget(value=50.0, priority=10, rule_code="TEST")

        # Act & Assert
        assert written.conflicts_with(50.2, tolerance=0.1) is True
        assert written.conflicts_with(49.8, tolerance=0.1) is True

    def test_when_tolerance_is_zero_then_exact_match_required(self):
        """Test that zero tolerance requires exact match for floats"""
        # Arrange
        written = WrittenTarget(value=50.0, priority=10, rule_code="TEST")

        # Act & Assert
        assert written.conflicts_with(50.0, tolerance=0.0) is False
        assert written.conflicts_with(50.001, tolerance=0.0) is True

    def test_when_int_values_with_tolerance_then_check_conflicts(self):
        """Test that integer values work correctly with tolerance"""
        # Arrange
        written = WrittenTarget(value=1, priority=10, rule_code="TEST")

        # Act & Assert
        # Exact match
        assert written.conflicts_with(1, tolerance=0.0) is False

        # Different values (like ON=1 vs OFF=0)
        assert written.conflicts_with(0, tolerance=0.0) is True

        # Even with tolerance, 0 and 1 differ by 1.0 > 0.1
        assert written.conflicts_with(0, tolerance=0.1) is True

    def test_when_mixed_int_float_comparison_then_handle_correctly(self):
        """Test that int and float values can be compared"""
        # Arrange
        written_int = WrittenTarget(value=50, priority=10, rule_code="TEST")
        written_float = WrittenTarget(value=50.0, priority=10, rule_code="TEST")

        # Act & Assert
        assert written_int.conflicts_with(50.0, tolerance=0.0) is False
        assert written_float.conflicts_with(50, tolerance=0.0) is False
        assert written_int.conflicts_with(50.1, tolerance=0.05) is True


class TestWrittenTargetIntegration:
    """Test WrittenTarget integration with dict"""

    def test_when_store_and_retrieve_from_dict_then_value_is_preserved(self):
        """Test storing and retrieving WrittenTarget in dict"""
        # Arrange
        written_targets: dict[str, WrittenTarget] = {}

        # Act
        written_targets["VFD_1_RW_HZ"] = WrittenTarget(value=50.0, priority=10, rule_code="TEMP_CTRL_01")

        # Assert
        retrieved = written_targets["VFD_1_RW_HZ"]
        assert retrieved.value == 50.0
        assert retrieved.priority == 10
        assert retrieved.rule_code == "TEMP_CTRL_01"

    def test_when_overwrite_in_dict_then_latest_value_is_returned(self):
        """Test overwriting WrittenTarget in dict"""
        # Arrange
        written_targets: dict[str, WrittenTarget] = {}

        # Act
        # First write
        written_targets["VFD_1_RW_HZ"] = WrittenTarget(value=50.0, priority=20, rule_code="RULE_A")

        # Higher priority write
        written_targets["VFD_1_RW_HZ"] = WrittenTarget(value=60.0, priority=10, rule_code="RULE_B")

        # Assert
        retrieved = written_targets["VFD_1_RW_HZ"]
        assert retrieved.value == 60.0
        assert retrieved.priority == 10
        assert retrieved.rule_code == "RULE_B"

    def test_when_simulate_turn_on_off_scenario_then_handle_correctly(self):
        """Test real-world ON/OFF scenario using integer values"""
        # Arrange
        written_targets: dict[str, WrittenTarget] = {}

        # Simulate TURN_ON (value=1)
        written_targets["VFD_1_RW_ON_OFF"] = WrittenTarget(value=1, priority=10, rule_code="TURN_ON")

        # Act - Try to TURN_OFF (value=0) with same priority
        written = written_targets["VFD_1_RW_ON_OFF"]

        # Assert
        assert written.value == 1
        assert written.conflicts_with(0, tolerance=0.0) is True  # ON (1) conflicts with OFF (0)
        assert written.conflicts_with(1, tolerance=0.0) is False  # ON (1) doesn't conflict with ON (1)
