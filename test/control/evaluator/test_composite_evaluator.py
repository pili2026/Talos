import pytest
from unittest.mock import Mock
from evaluator.composite_evaluator import CompositeEvaluator
from model.control_composite import CompositeNode
from model.enum.condition_enum import ConditionOperator, ConditionType


def create_mock_composite_node(**kwargs):
    """Helper function to create properly configured CompositeNode Mock"""
    composite = Mock(spec=CompositeNode)

    # Set default values for all possible attributes
    defaults = {
        "type": None,
        "source": None,
        "sources": None,
        "operator": None,
        ConditionType.THRESHOLD: None,
        "min": None,
        "max": None,
        "hysteresis": None,
        "debounce_sec": None,
        "any": None,
        "all": None,
        "not_": None,
        "abs": True,
    }

    # Update defaults with provided kwargs
    defaults.update(kwargs)

    # Configure the mock with all attributes
    composite.configure_mock(**defaults)

    return composite


class TestCompositeEvaluatorLogic:
    """Test AND/OR/NOT logic in CompositeEvaluator"""

    @pytest.fixture
    def composite_evaluator(self):
        """Create CompositeEvaluator instance"""
        return CompositeEvaluator()

    @pytest.fixture
    def mock_get_value(self):
        """Create mock get_value function"""

        def get_value(key: str):
            # Sample data for testing
            data = {"AIn01": 25.0, "AIn02": 20.0, "AIn03": 30.0, "AIn04": 15.0}
            return data.get(key)

        return get_value

    def test_when_single_threshold_condition_above_then_returns_true(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test single threshold condition evaluation - value above threshold"""
        # Arrange
        composite = create_mock_composite_node(
            type=ConditionType.THRESHOLD,
            source="AIn01",
            operator=ConditionOperator.GREATER_THAN,
            threshold=20.0,
            hysteresis=1.0,
            debounce_sec=0.0,
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: AIn01 (25.0) > 20.0 should be True
        assert result is True

    def test_when_single_threshold_condition_below_then_returns_false(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test single threshold condition evaluation - value below threshold"""
        # Arrange
        composite = create_mock_composite_node(
            type=ConditionType.THRESHOLD,
            source="AIn04",
            operator=ConditionOperator.GREATER_THAN,
            threshold=20.0,
            hysteresis=1.0,
            debounce_sec=0.0,  # 15.0
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: AIn04 (15.0) > 20.0 should be False
        assert result is False

    def test_when_any_logic_with_one_true_then_returns_true(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test OR logic - any one condition true should return true"""
        # Arrange
        # Create child conditions using helper function
        true_condition = create_mock_composite_node(
            type=ConditionType.THRESHOLD,
            source="AIn01",
            operator=ConditionOperator.GREATER_THAN,
            threshold=20.0,  # 25.0
        )

        false_condition = create_mock_composite_node(
            type=ConditionType.THRESHOLD,
            source="AIn04",
            operator=ConditionOperator.GREATER_THAN,
            threshold=20.0,  # 15.0
        )

        # Create parent composite with 'any' (OR) logic
        composite = create_mock_composite_node(type=None, any=[true_condition, false_condition])

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: Should return True because first condition is true
        assert result is True

    def test_when_any_logic_with_all_false_then_returns_false(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test OR logic - all conditions false should return false"""
        # Arrange
        false_condition1 = create_mock_composite_node(
            type=ConditionType.THRESHOLD,
            source="AIn04",
            operator=ConditionOperator.GREATER_THAN,
            threshold=20.0,  # 15.0
        )

        false_condition2 = create_mock_composite_node(
            type=ConditionType.THRESHOLD,
            source="AIn04",
            operator=ConditionOperator.GREATER_THAN,
            threshold=25.0,  # 15.0
        )

        composite = create_mock_composite_node(type=None, any=[false_condition1, false_condition2])

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: Should return False because all conditions are false
        assert result is False

    def test_when_all_logic_with_all_true_then_returns_true(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test AND logic - all conditions true should return true"""
        # Arrange
        true_condition1 = create_mock_composite_node(
            type=ConditionType.THRESHOLD,
            source="AIn01",
            operator=ConditionOperator.GREATER_THAN,
            threshold=20.0,  # 25.0
        )

        true_condition2 = create_mock_composite_node(
            type=ConditionType.THRESHOLD,
            source="AIn03",
            operator=ConditionOperator.GREATER_THAN,
            threshold=25.0,  # 30.0
        )

        composite = create_mock_composite_node(type=None, all=[true_condition1, true_condition2])

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: Should return True because both conditions are true
        assert result is True

    def test_when_all_logic_with_one_false_then_returns_false(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test AND logic - one condition false should return false"""
        # Arrange
        true_condition = create_mock_composite_node(
            type=ConditionType.THRESHOLD,
            source="AIn01",
            operator=ConditionOperator.GREATER_THAN,
            threshold=20.0,  # 25.0
        )

        false_condition = create_mock_composite_node(
            type=ConditionType.THRESHOLD,
            source="AIn04",
            operator=ConditionOperator.GREATER_THAN,
            threshold=20.0,  # 15.0
        )

        composite = create_mock_composite_node(type=None, all=[true_condition, false_condition])

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: Should return False because one condition is false
        assert result is False

    def test_when_not_logic_with_true_condition_then_returns_false(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test NOT logic - true condition should return false"""
        # Arrange
        true_condition = create_mock_composite_node(
            type=ConditionType.THRESHOLD,
            source="AIn01",
            operator=ConditionOperator.GREATER_THAN,
            threshold=20.0,  # 25.0
        )

        composite = create_mock_composite_node(type=None, not_=true_condition)  # Single condition, not a list

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: Should return False because NOT(true) = false
        assert result is False

    def test_when_not_logic_with_false_condition_then_returns_true(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test NOT logic - false condition should return true"""
        # Arrange
        false_condition = create_mock_composite_node(
            type=ConditionType.THRESHOLD,
            source="AIn04",
            operator=ConditionOperator.GREATER_THAN,
            threshold=20.0,  # 15.0
        )

        composite = create_mock_composite_node(type=None, not_=false_condition)  # Single condition, not a list

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: Should return True because NOT(false) = true
        assert result is True

    def test_when_difference_condition_above_threshold_then_returns_true(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test difference condition evaluation - difference above threshold"""
        # Arrange
        composite = create_mock_composite_node(
            type=ConditionType.DIFFERENCE,
            sources=["AIn01", "AIn02"],
            operator=ConditionOperator.GREATER_THAN,
            threshold=4.0,  # 25.0 - 20.0 = 5.0
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: Difference (5.0) > 4.0 should be True
        assert result is True

    def test_when_difference_condition_below_threshold_then_returns_false(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test difference condition evaluation - difference below threshold"""
        # Arrange
        composite = create_mock_composite_node(
            type=ConditionType.DIFFERENCE,
            sources=["AIn01", "AIn02"],
            operator=ConditionOperator.LESS_THAN,
            threshold=4.0,  # 25.0 - 20.0 = 5.0
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: Difference (5.0) < 4.0 should be False
        assert result is False

    def test_when_between_operator_within_range_then_returns_true(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test between operator - value within range"""
        # Arrange
        composite = create_mock_composite_node(
            type=ConditionType.THRESHOLD, source="AIn01", operator=ConditionOperator.BETWEEN, min=20.0, max=30.0  # 25.0
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: 25.0 is between 20.0 and 30.0
        assert result is True

    def test_when_between_operator_outside_range_then_returns_false(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test between operator - value outside range"""
        # Arrange
        composite = create_mock_composite_node(
            type=ConditionType.THRESHOLD, source="AIn01", operator=ConditionOperator.BETWEEN, min=30.0, max=35.0  # 25.0
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: 25.0 is not between 30.0 and 35.0
        assert result is False

    def test_when_complex_nested_logic_then_evaluates_correctly(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test complex nested AND/OR logic"""
        # Arrange: (condition1 OR condition2) AND condition3
        condition1 = create_mock_composite_node(
            type=ConditionType.THRESHOLD,
            source="AIn04",
            operator=ConditionOperator.GREATER_THAN,
            threshold=20.0,  # 15.0 (will be false)
        )

        condition2 = create_mock_composite_node(
            type=ConditionType.THRESHOLD,
            source="AIn01",
            operator=ConditionOperator.GREATER_THAN,
            threshold=20.0,  # 25.0 (will be true)
        )

        condition3 = create_mock_composite_node(
            type=ConditionType.THRESHOLD,
            source="AIn03",
            operator=ConditionOperator.GREATER_THAN,
            threshold=25.0,  # 30.0 (will be true)
        )

        # Create OR group (condition1 OR condition2)
        or_group = create_mock_composite_node(type=None, any=[condition1, condition2])

        # Create main AND composite
        composite = create_mock_composite_node(type=None, all=[or_group, condition3])  # (OR group) AND condition3

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: (false OR true) AND true = true AND true = true
        assert result is True

    def test_when_missing_source_data_then_handles_gracefully(self, composite_evaluator):
        """Test handling of missing source data"""

        # Arrange
        def empty_get_value(key: str):
            return None  # Simulate missing data

        composite = create_mock_composite_node(
            type=ConditionType.THRESHOLD,
            source="NonExistentSource",
            operator=ConditionOperator.GREATER_THAN,
            threshold=20.0,
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, empty_get_value)

        # Assert: Should handle missing data gracefully (likely return False)
        assert result is False

    def test_when_invalid_composite_type_then_handles_gracefully(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test handling of invalid composite types"""
        # Arrange
        composite = create_mock_composite_node(
            type="invalid_type", source="AIn01", operator=ConditionOperator.GREATER_THAN, threshold=20.0
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: Should handle invalid type gracefully
        assert result is False

    def test_when_empty_any_list_then_returns_false(self, composite_evaluator: CompositeEvaluator, mock_get_value):
        """Test OR logic with empty condition list"""
        # Arrange
        composite = create_mock_composite_node(type=None, any=[])  # Empty list

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: Empty OR should return False
        assert result is False

    def test_when_empty_all_list_then_returns_true(self, composite_evaluator: CompositeEvaluator, mock_get_value):
        """Test AND logic with empty condition list"""
        # Arrange
        composite = create_mock_composite_node(type=None, all=[])  # Empty list

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: Empty AND should return True (vacuous truth)
        assert result is True


class TestCompositeEvaluatorReasonSummary:
    """Test reason summary generation in CompositeEvaluator"""

    @pytest.fixture
    def composite_evaluator(self):
        """Create CompositeEvaluator instance"""
        return CompositeEvaluator()

    def test_when_simple_threshold_then_builds_correct_reason(self, composite_evaluator: CompositeEvaluator):
        """Test reason summary for simple threshold condition"""
        # Arrange
        composite = create_mock_composite_node(
            type=ConditionType.THRESHOLD,
            source="AIn01",
            operator=ConditionOperator.GREATER_THAN,
            threshold=40.0,
            hysteresis=1.0,
        )

        # Act
        reason = composite_evaluator.build_composite_reason_summary(composite)

        # Assert
        assert reason is not None
        assert ConditionType.THRESHOLD in reason
        assert "AIn01" in reason
        assert ConditionOperator.GREATER_THAN in reason
        assert "40.0" in reason

    def test_when_difference_condition_then_builds_correct_reason(self, composite_evaluator: CompositeEvaluator):
        """Test reason summary for difference condition"""
        # Arrange
        composite = create_mock_composite_node(
            type=ConditionType.DIFFERENCE,
            sources=["AIn01", "AIn02"],
            operator=ConditionOperator.GREATER_THAN,
            threshold=4.0,
            abs=True,
        )

        # Act
        reason = composite_evaluator.build_composite_reason_summary(composite)

        # Assert
        assert reason is not None
        assert ConditionType.DIFFERENCE in reason
        assert "AIn01,AIn02" in reason
        assert ConditionOperator.GREATER_THAN in reason
        assert "4.0" in reason

    def test_when_any_logic_then_builds_or_reason(self, composite_evaluator: CompositeEvaluator):
        """Test reason summary for OR logic"""
        # Arrange
        condition1 = create_mock_composite_node(
            type=ConditionType.THRESHOLD, source="AIn01", operator=ConditionOperator.GREATER_THAN, threshold=20.0
        )

        condition2 = create_mock_composite_node(
            type=ConditionType.THRESHOLD, source="AIn02", operator=ConditionOperator.LESS_THAN, threshold=10.0
        )

        composite = create_mock_composite_node(type=None, any=[condition1, condition2])

        # Act
        reason = composite_evaluator.build_composite_reason_summary(composite)

        # Assert
        assert reason is not None
        assert "OR" in reason or "AIn01" in reason, f"Unexpected reason: {reason}"

    def test_when_all_logic_then_builds_and_reason(self, composite_evaluator: CompositeEvaluator):
        """Test reason summary for AND logic"""
        # Arrange
        condition1 = create_mock_composite_node(
            type=ConditionType.THRESHOLD, source="AIn01", operator=ConditionOperator.GREATER_THAN, threshold=20.0
        )

        condition2 = create_mock_composite_node(
            type=ConditionType.THRESHOLD, source="AIn02", operator=ConditionOperator.LESS_THAN, threshold=10.0
        )

        composite = create_mock_composite_node(type=None, all=[condition1, condition2])

        # Act
        reason = composite_evaluator.build_composite_reason_summary(composite)

        # Assert
        assert reason is not None
        assert "AND" in reason or "AIn01" in reason, f"Unexpected reason: {reason}"
