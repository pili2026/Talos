"""
Unit tests for aggregate condition types (AVERAGE, SUM, MIN, MAX).
Add these tests to test/control/evaluator/test_composite_evaluator.py

Naming convention: test_when_{condition}_then_{expected_behavior}
"""

from unittest.mock import Mock

import pytest

from evaluator.composite_evaluator import CompositeEvaluator
from model.control_composite import CompositeNode
from model.enum.condition_enum import ConditionOperator, ConditionType


def create_mock_composite_node(**kwargs):
    """Helper function to create properly configured CompositeNode Mock"""
    composite = Mock(spec=CompositeNode)

    # Set default values for all possible attributes
    defaults = {
        "type": None,
        "sources": None,
        "operator": None,
        "threshold": None,
        "min": None,
        "max": None,
        "hysteresis": None,
        "debounce_sec": None,
        "any": None,
        "all": None,
        "not_": None,
        "abs": False,
    }

    # Update defaults with provided kwargs
    defaults.update(kwargs)

    # Configure the mock with all attributes
    composite.configure_mock(**defaults)

    return composite


class TestCompositeEvaluatorAggregateConditions:
    """Test aggregate condition types (AVERAGE, SUM, MIN, MAX)"""

    @pytest.fixture
    def composite_evaluator(self):
        """Create CompositeEvaluator instance"""
        return CompositeEvaluator()

    @pytest.fixture
    def mock_get_value(self):
        """Create mock get_value function with sample data"""

        def get_value(key: str):
            # Sample data for testing
            data = {
                "AIn01": 10.0,
                "AIn02": 20.0,
                "AIn03": 30.0,
                "AIn04": 40.0,
            }
            return data.get(key)

        return get_value

    # ========================================
    # AVERAGE condition tests
    # ========================================

    def test_when_average_exceeds_threshold_then_returns_true(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test average condition evaluation when average exceeds threshold"""
        # Arrange: avg([10, 20, 30, 40]) = 25.0
        composite = create_mock_composite_node(
            type=ConditionType.AVERAGE,
            sources=["AIn01", "AIn02", "AIn03", "AIn04"],
            operator=ConditionOperator.GREATER_THAN,
            threshold=20.0,
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: 25.0 > 20.0
        assert result is True

    def test_when_average_below_threshold_then_returns_false(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test average condition evaluation when average is below threshold"""
        # Arrange: avg([10, 20, 30, 40]) = 25.0
        composite = create_mock_composite_node(
            type=ConditionType.AVERAGE,
            sources=["AIn01", "AIn02", "AIn03", "AIn04"],
            operator=ConditionOperator.GREATER_THAN,
            threshold=30.0,
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: 25.0 > 30.0 is False
        assert result is False

    def test_when_average_within_range_then_returns_true(self, composite_evaluator: CompositeEvaluator, mock_get_value):
        """Test average condition with BETWEEN operator when value is within range"""
        # Arrange: avg([10, 20, 30]) = 20.0
        composite = create_mock_composite_node(
            type=ConditionType.AVERAGE,
            sources=["AIn01", "AIn02", "AIn03"],
            operator=ConditionOperator.BETWEEN,
            min=15.0,
            max=25.0,
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: 20.0 is between 15.0 and 25.0
        assert result is True

    def test_when_average_outside_range_then_returns_false(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test average condition with BETWEEN operator when value is outside range"""
        # Arrange: avg([10, 20, 30, 40]) = 25.0
        composite = create_mock_composite_node(
            type=ConditionType.AVERAGE,
            sources=["AIn01", "AIn02", "AIn03", "AIn04"],
            operator=ConditionOperator.BETWEEN,
            min=30.0,
            max=40.0,
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: 25.0 is not between 30.0 and 40.0
        assert result is False

    def test_when_average_has_partial_missing_values_then_uses_available_values(
        self, composite_evaluator: CompositeEvaluator
    ):
        """Test average condition handles partial missing values by using available values"""

        # Arrange
        def partial_get_value(key: str):
            # Only 3 out of 4 values available
            data = {"AIn01": 10.0, "AIn02": 20.0, "AIn03": 30.0}
            return data.get(key)

        # avg([10, 20, 30]) = 20.0
        composite = create_mock_composite_node(
            type=ConditionType.AVERAGE,
            sources=["AIn01", "AIn02", "AIn03", "AIn04"],  # AIn04 missing
            operator=ConditionOperator.GREATER_THAN,
            threshold=15.0,
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, partial_get_value)

        # Assert: Should use available values (avg = 20.0 > 15.0)
        assert result is True

    def test_when_average_has_all_missing_values_then_returns_false(self, composite_evaluator: CompositeEvaluator):
        """Test average condition returns false when all source values are missing"""

        # Arrange
        def empty_get_value(key: str):
            return None  # All values missing

        composite = create_mock_composite_node(
            type=ConditionType.AVERAGE,
            sources=["AIn01", "AIn02", "AIn03"],
            operator=ConditionOperator.GREATER_THAN,
            threshold=20.0,
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, empty_get_value)

        # Assert: No valid values → False
        assert result is False

    def test_when_average_equal_to_threshold_then_returns_true(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test average condition with EQUAL operator when value equals threshold"""
        # Arrange: avg([10, 20, 30]) = 20.0
        composite = create_mock_composite_node(
            type=ConditionType.AVERAGE,
            sources=["AIn01", "AIn02", "AIn03"],
            operator=ConditionOperator.EQUAL,
            threshold=20.0,
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: 20.0 == 20.0
        assert result is True

    # ========================================
    # SUM condition tests
    # ========================================

    def test_when_sum_exceeds_threshold_then_returns_true(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test sum condition evaluation when sum exceeds threshold"""
        # Arrange: sum([10, 20, 30]) = 60.0
        composite = create_mock_composite_node(
            type=ConditionType.SUM,
            sources=["AIn01", "AIn02", "AIn03"],
            operator=ConditionOperator.GREATER_THAN,
            threshold=50.0,
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: 60.0 > 50.0
        assert result is True

    def test_when_sum_below_threshold_then_returns_false(self, composite_evaluator: CompositeEvaluator, mock_get_value):
        """Test sum condition evaluation when sum is below threshold"""
        # Arrange: sum([10, 20]) = 30.0
        composite = create_mock_composite_node(
            type=ConditionType.SUM,
            sources=["AIn01", "AIn02"],
            operator=ConditionOperator.LESS_THAN,
            threshold=20.0,
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: 30.0 < 20.0 is False
        assert result is False

    def test_when_sum_within_range_then_returns_true(self, composite_evaluator: CompositeEvaluator, mock_get_value):
        """Test sum condition with BETWEEN operator when value is within range"""
        # Arrange: sum([10, 20, 30, 40]) = 100.0
        composite = create_mock_composite_node(
            type=ConditionType.SUM,
            sources=["AIn01", "AIn02", "AIn03", "AIn04"],
            operator=ConditionOperator.BETWEEN,
            min=90.0,
            max=110.0,
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: 100.0 is between 90.0 and 110.0
        assert result is True

    def test_when_sum_has_partial_missing_values_then_uses_available_values(
        self, composite_evaluator: CompositeEvaluator
    ):
        """Test sum condition handles partial missing values by using available values"""

        # Arrange
        def partial_get_value(key: str):
            data = {"AIn01": 10.0, "AIn02": 20.0}  # Only 2 out of 3
            return data.get(key)

        # sum([10, 20]) = 30.0
        composite = create_mock_composite_node(
            type=ConditionType.SUM,
            sources=["AIn01", "AIn02", "AIn03"],  # AIn03 missing
            operator=ConditionOperator.GREATER_THAN,
            threshold=25.0,
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, partial_get_value)

        # Assert: 30.0 > 25.0
        assert result is True

    # ========================================
    # MIN condition tests
    # ========================================

    def test_when_min_below_threshold_then_returns_true(self, composite_evaluator: CompositeEvaluator, mock_get_value):
        """Test min condition evaluation when minimum value is below threshold"""
        # Arrange: min([10, 20, 30]) = 10.0
        composite = create_mock_composite_node(
            type=ConditionType.MIN,
            sources=["AIn01", "AIn02", "AIn03"],
            operator=ConditionOperator.LESS_THAN,
            threshold=15.0,
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: 10.0 < 15.0
        assert result is True

    def test_when_min_exceeds_threshold_then_returns_false(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test min condition evaluation when minimum value exceeds threshold"""
        # Arrange: min([10, 20, 30]) = 10.0
        composite = create_mock_composite_node(
            type=ConditionType.MIN,
            sources=["AIn01", "AIn02", "AIn03"],
            operator=ConditionOperator.GREATER_THAN,
            threshold=15.0,
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: 10.0 > 15.0 is False
        assert result is False

    def test_when_min_within_range_then_returns_true(self, composite_evaluator: CompositeEvaluator, mock_get_value):
        """Test min condition with BETWEEN operator when value is within range"""
        # Arrange: min([10, 20, 30]) = 10.0
        composite = create_mock_composite_node(
            type=ConditionType.MIN,
            sources=["AIn01", "AIn02", "AIn03"],
            operator=ConditionOperator.BETWEEN,
            min=5.0,
            max=15.0,
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: 10.0 is between 5.0 and 15.0
        assert result is True

    # ========================================
    # MAX condition tests
    # ========================================

    def test_when_max_exceeds_threshold_then_returns_true(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test max condition evaluation when maximum value exceeds threshold"""
        # Arrange: max([10, 20, 30, 40]) = 40.0
        composite = create_mock_composite_node(
            type=ConditionType.MAX,
            sources=["AIn01", "AIn02", "AIn03", "AIn04"],
            operator=ConditionOperator.GREATER_THAN,
            threshold=35.0,
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: 40.0 > 35.0
        assert result is True

    def test_when_max_below_threshold_then_returns_false(self, composite_evaluator: CompositeEvaluator, mock_get_value):
        """Test max condition evaluation when maximum value is below threshold"""
        # Arrange: max([10, 20]) = 20.0
        composite = create_mock_composite_node(
            type=ConditionType.MAX,
            sources=["AIn01", "AIn02"],
            operator=ConditionOperator.LESS_THAN,
            threshold=15.0,
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: 20.0 < 15.0 is False
        assert result is False

    def test_when_max_equal_to_threshold_then_returns_true(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test max condition with EQUAL operator when value equals threshold"""
        # Arrange: max([10, 20, 30, 40]) = 40.0
        composite = create_mock_composite_node(
            type=ConditionType.MAX,
            sources=["AIn01", "AIn02", "AIn03", "AIn04"],
            operator=ConditionOperator.EQUAL,
            threshold=40.0,
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: 40.0 == 40.0
        assert result is True

    def test_when_max_within_range_then_returns_true(self, composite_evaluator: CompositeEvaluator, mock_get_value):
        """Test max condition with BETWEEN operator when value is within range"""
        # Arrange: max([10, 20, 30, 40]) = 40.0
        composite = create_mock_composite_node(
            type=ConditionType.MAX,
            sources=["AIn01", "AIn02", "AIn03", "AIn04"],
            operator=ConditionOperator.BETWEEN,
            min=35.0,
            max=45.0,
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: 40.0 is between 35.0 and 45.0
        assert result is True

    # ========================================
    # Reason summary tests
    # ========================================

    def test_when_average_condition_evaluated_then_builds_correct_reason(self, composite_evaluator: CompositeEvaluator):
        """Test reason summary generation for AVERAGE condition"""
        # Arrange
        composite = create_mock_composite_node(
            type=ConditionType.AVERAGE,
            sources=["AIn01", "AIn02", "AIn03"],
            operator=ConditionOperator.GREATER_THAN,
            threshold=20.0,
        )

        # Act
        reason = composite_evaluator.build_composite_reason_summary(composite)

        # Assert
        assert reason is not None
        assert "average" in reason.lower()
        assert "AIn01,AIn02,AIn03" in reason or "AIn01" in reason
        assert "gt" in reason.lower() or ">" in reason
        assert "20.0" in reason

    def test_when_sum_condition_with_between_then_builds_correct_reason(self, composite_evaluator: CompositeEvaluator):
        """Test reason summary generation for SUM condition with BETWEEN operator"""
        # Arrange
        composite = create_mock_composite_node(
            type=ConditionType.SUM,
            sources=["AIn01", "AIn02"],
            operator=ConditionOperator.BETWEEN,
            min=10.0,
            max=50.0,
        )

        # Act
        reason = composite_evaluator.build_composite_reason_summary(composite)

        # Assert
        assert reason is not None
        assert "sum" in reason.lower()
        assert "AIn01,AIn02" in reason or "AIn01" in reason
        assert "between" in reason.lower()
        assert "10.0" in reason and "50.0" in reason

    def test_when_min_condition_evaluated_then_builds_correct_reason(self, composite_evaluator: CompositeEvaluator):
        """Test reason summary generation for MIN condition"""
        # Arrange
        composite = create_mock_composite_node(
            type=ConditionType.MIN,
            sources=["AIn01", "AIn02", "AIn03", "AIn04"],
            operator=ConditionOperator.LESS_THAN,
            threshold=15.0,
        )

        # Act
        reason = composite_evaluator.build_composite_reason_summary(composite)

        # Assert
        assert reason is not None
        assert "min" in reason.lower()
        assert "lt" in reason.lower() or "<" in reason
        assert "15.0" in reason

    def test_when_max_condition_evaluated_then_builds_correct_reason(self, composite_evaluator: CompositeEvaluator):
        """Test reason summary generation for MAX condition"""
        # Arrange
        composite = create_mock_composite_node(
            type=ConditionType.MAX,
            sources=["AIn01", "AIn02"],
            operator=ConditionOperator.EQUAL,
            threshold=40.0,
        )

        # Act
        reason = composite_evaluator.build_composite_reason_summary(composite)

        # Assert
        assert reason is not None
        assert "max" in reason.lower()
        assert "eq" in reason.lower() or "=" in reason
        assert "40.0" in reason

    # ========================================
    # Complex nested conditions
    # ========================================

    def test_when_nested_average_and_threshold_both_match_then_returns_true(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test complex nested condition with aggregate and threshold when both match"""
        # Arrange: (avg([10,20,30]) > 15) AND (AIn04 < 50)
        avg_condition = create_mock_composite_node(
            type=ConditionType.AVERAGE,
            sources=["AIn01", "AIn02", "AIn03"],
            operator=ConditionOperator.GREATER_THAN,
            threshold=15.0,
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        threshold_condition = create_mock_composite_node(
            type=ConditionType.THRESHOLD,
            sources=["AIn04"],
            operator=ConditionOperator.LESS_THAN,
            threshold=50.0,
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        composite = create_mock_composite_node(type=None, all=[avg_condition, threshold_condition])

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: (20.0 > 15.0) AND (40.0 < 50.0) = True AND True = True
        assert result is True

    def test_when_nested_average_or_sum_either_matches_then_returns_true(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test nested condition with OR logic when either aggregate matches"""
        # Arrange: (avg([10,20]) < 10) OR (sum([30,40]) > 50)
        avg_condition = create_mock_composite_node(
            type=ConditionType.AVERAGE,
            sources=["AIn01", "AIn02"],
            operator=ConditionOperator.LESS_THAN,
            threshold=10.0,  # avg=15, will be false
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        sum_condition = create_mock_composite_node(
            type=ConditionType.SUM,
            sources=["AIn03", "AIn04"],
            operator=ConditionOperator.GREATER_THAN,
            threshold=50.0,  # sum=70, will be true
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        composite = create_mock_composite_node(type=None, any=[avg_condition, sum_condition])

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: (15.0 < 10.0) OR (70.0 > 50.0) = False OR True = True
        assert result is True

    def test_when_not_aggregate_condition_inverted_then_returns_correct_result(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test NOT logic with aggregate condition"""
        # Arrange: NOT(max([10,20,30,40]) > 50)
        max_condition = create_mock_composite_node(
            type=ConditionType.MAX,
            sources=["AIn01", "AIn02", "AIn03", "AIn04"],
            operator=ConditionOperator.GREATER_THAN,
            threshold=50.0,  # max=40, condition is false
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        composite = create_mock_composite_node(type=None, not_=max_condition)

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: NOT(40.0 > 50.0) = NOT(False) = True
        assert result is True

    # ========================================
    # Edge cases and error handling
    # ========================================

    def test_when_aggregate_has_single_source_then_returns_false(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test aggregate condition with only one source returns false"""
        # Arrange: Aggregate requires at least 2 sources
        composite = create_mock_composite_node(
            type=ConditionType.AVERAGE,
            sources=["AIn01"],  # Only 1 source
            operator=ConditionOperator.GREATER_THAN,
            threshold=5.0,
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert: Should return False due to insufficient sources
        assert result is False

    def test_when_aggregate_has_empty_sources_then_returns_false(
        self, composite_evaluator: CompositeEvaluator, mock_get_value
    ):
        """Test aggregate condition with empty sources list returns false"""
        # Arrange
        composite = create_mock_composite_node(
            type=ConditionType.SUM,
            sources=[],  # Empty sources
            operator=ConditionOperator.GREATER_THAN,
            threshold=10.0,
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, mock_get_value)

        # Assert
        assert result is False

    def test_when_aggregate_has_nan_values_then_skips_nan(self, composite_evaluator: CompositeEvaluator):
        """Test aggregate condition skips NaN values and uses valid values"""
        # Arrange
        import math

        def get_value_with_nan(key: str):
            data = {"AIn01": 10.0, "AIn02": math.nan, "AIn03": 30.0}
            return data.get(key)

        # avg([10, 30]) = 20.0 (skipping NaN)
        composite = create_mock_composite_node(
            type=ConditionType.AVERAGE,
            sources=["AIn01", "AIn02", "AIn03"],
            operator=ConditionOperator.GREATER_THAN,
            threshold=15.0,
            hysteresis=0.0,
            debounce_sec=0.0,
        )

        # Act
        result = composite_evaluator.evaluate_composite_node(composite, get_value_with_nan)

        # Assert: avg([10, 30]) = 20.0 > 15.0
        assert result is True


class TestCompositeNodeAggregateValidation:
    """Test validation logic for aggregate condition types"""

    def test_when_average_has_less_than_two_sources_then_validation_fails(self):
        """Test that AVERAGE with fewer than 2 sources is marked invalid"""
        # Arrange & Act
        node = CompositeNode(
            type=ConditionType.AVERAGE,
            sources=["AIn01"],  # Only 1 source (invalid)
            operator=ConditionOperator.GREATER_THAN,
            threshold=20.0,
        )

        # Assert
        assert node.invalid is True

    def test_when_sum_has_duplicate_sources_then_validation_fails(self):
        """Test that SUM with duplicate sources is marked invalid"""
        # Arrange & Act
        node = CompositeNode(
            type=ConditionType.SUM,
            sources=["AIn01", "AIn01"],  # Duplicate (invalid)
            operator=ConditionOperator.GREATER_THAN,
            threshold=50.0,
        )

        # Assert
        assert node.invalid is True

    def test_when_min_has_no_operator_then_validation_fails(self):
        """Test that MIN without operator is marked invalid"""
        # Arrange & Act
        node = CompositeNode(
            type=ConditionType.MIN,
            sources=["AIn01", "AIn02"],
            # No operator (invalid)
            threshold=10.0,
        )

        # Assert
        assert node.invalid is True

    def test_when_max_between_has_no_min_max_then_validation_fails(self):
        """Test that MAX with BETWEEN but no min/max is marked invalid"""
        # Arrange & Act
        node = CompositeNode(
            type=ConditionType.MAX,
            sources=["AIn01", "AIn02"],
            operator=ConditionOperator.BETWEEN,
            # No min/max specified (invalid)
        )

        # Assert
        assert node.invalid is True

    def test_when_average_has_valid_config_then_validation_passes(self):
        """Test that valid AVERAGE configuration passes validation"""
        # Arrange & Act
        node = CompositeNode(
            type=ConditionType.AVERAGE,
            sources=["AIn01", "AIn02", "AIn03"],
            operator=ConditionOperator.GREATER_THAN,
            threshold=25.0,
        )

        # Assert
        assert node.invalid is False

    def test_when_sum_has_empty_sources_then_validation_fails(self):
        """Test that SUM with empty sources list is marked invalid"""
        # Arrange & Act
        node = CompositeNode(
            type=ConditionType.SUM,
            sources=[],  # Empty (invalid)
            operator=ConditionOperator.GREATER_THAN,
            threshold=50.0,
        )

        # Assert
        assert node.invalid is True

    def test_when_min_gt_has_no_threshold_then_validation_fails(self):
        """Test that MIN with GT operator but no threshold is marked invalid"""
        # Arrange & Act
        node = CompositeNode(
            type=ConditionType.MIN,
            sources=["AIn01", "AIn02", "AIn03"],
            operator=ConditionOperator.GREATER_THAN,
            # No threshold (invalid)
        )

        # Assert
        assert node.invalid is True

    def test_when_max_between_has_valid_min_max_then_validation_passes(self):
        """Test that MAX with BETWEEN and valid min/max passes validation"""
        # Arrange & Act
        node = CompositeNode(
            type=ConditionType.MAX,
            sources=["AIn01", "AIn02"],
            operator=ConditionOperator.BETWEEN,
            min=10.0,
            max=50.0,
        )

        # Assert
        assert node.invalid is False

    def test_when_average_has_three_unique_sources_then_validation_passes(self):
        """Test that AVERAGE with 3 unique sources passes validation"""
        # Arrange & Act
        node = CompositeNode(
            type=ConditionType.AVERAGE,
            sources=["AIn01", "AIn02", "AIn03"],
            operator=ConditionOperator.LESS_THAN,
            threshold=30.0,
        )

        # Assert
        assert node.invalid is False
