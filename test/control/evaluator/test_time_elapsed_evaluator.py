"""
Unit Tests for Time-Elapsed Control Conditions

Tests the time_elapsed condition evaluation logic integrated into CompositeEvaluator with:
- First execution (immediate trigger)
- Interval not elapsed (no trigger)
- Interval elapsed (trigger)
- System restart persistence
- Error handling
"""

import logging
from datetime import datetime, timedelta
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from core.evaluator.composite_evaluator import CompositeEvaluator
from core.model.control_composite import CompositeNode
from core.model.enum.condition_enum import ConditionType


class TestTimeElapsedEvaluator:
    """Unit tests for time_elapsed condition evaluation in CompositeEvaluator"""

    @pytest.fixture
    def tz(self):
        return ZoneInfo("Asia/Taipei")

    @pytest.fixture
    def mock_execution_store(self):
        """Create mock ControlExecutionStore"""
        store = Mock()
        store.get_last_execution = Mock(return_value=None)
        store.update_execution = Mock()
        return store

    @pytest.fixture
    def mock_composite_node(self):
        """Create mock CompositeNode with time_elapsed type"""
        node = Mock()
        node.type = ConditionType.TIME_ELAPSED
        node.interval_hours = 4.0
        return node

    @pytest.fixture
    def evaluator(self, mock_execution_store):
        """Create CompositeEvaluator with execution_store"""
        return CompositeEvaluator(execution_store=mock_execution_store, timezone="Asia/Taipei")

    # ========================================
    # Test: First Execution
    # ========================================

    def test_when_first_execution_then_triggers_immediately(
        self, evaluator, mock_execution_store, mock_composite_node, tz
    ):
        """Test that first execution (no history) triggers immediately"""
        # Arrange
        mock_execution_store.get_last_execution.return_value = None
        evaluator.set_evaluation_context("FREQ_STEPDOWN_4H", "TECO_VFD", "4")

        # Act
        result = evaluator._evaluate_time_elapsed_leaf(mock_composite_node)

        # Assert
        assert result is True
        mock_execution_store.get_last_execution.assert_called_once_with("FREQ_STEPDOWN_4H")
        mock_execution_store.update_execution.assert_called_once()

        # Verify update_execution was called with correct parameters
        call_args = mock_execution_store.update_execution.call_args[0]
        assert call_args[0] == "FREQ_STEPDOWN_4H"
        assert isinstance(call_args[1], datetime)
        assert call_args[2] == "TECO_VFD"
        assert call_args[3] == "4"

    # ========================================
    # Test: Interval Not Elapsed
    # ========================================

    def test_when_interval_not_elapsed_then_does_not_trigger(
        self, evaluator, mock_execution_store, mock_composite_node, tz
    ):
        """Test that condition does not trigger when interval hasn't elapsed"""
        # Arrange
        now = datetime.now(tz)
        last_execution = now - timedelta(hours=2)  # Only 2 hours ago (need 4)

        mock_execution_store.get_last_execution.return_value = last_execution
        evaluator.set_evaluation_context("FREQ_STEPDOWN_4H", "TECO_VFD", "4")

        # Act
        result = evaluator._evaluate_time_elapsed_leaf(mock_composite_node)

        # Assert
        assert result is False
        mock_execution_store.get_last_execution.assert_called_once()
        mock_execution_store.update_execution.assert_not_called()

    # ========================================
    # Test: Interval Elapsed
    # ========================================

    def test_when_interval_elapsed_then_triggers(self, evaluator, mock_execution_store, mock_composite_node, tz):
        """Test that condition triggers when interval has elapsed"""
        # Arrange
        now = datetime.now(tz)
        last_execution = now - timedelta(hours=4.5)  # 4.5 hours ago (>= 4)

        mock_execution_store.get_last_execution.return_value = last_execution
        evaluator.set_evaluation_context("FREQ_STEPDOWN_4H", "TECO_VFD", "4")

        # Act
        result = evaluator._evaluate_time_elapsed_leaf(mock_composite_node)

        # Assert
        assert result is True
        mock_execution_store.get_last_execution.assert_called_once()
        mock_execution_store.update_execution.assert_called_once()

    # ========================================
    # Test: Exactly At Interval
    # ========================================

    def test_when_exactly_at_interval_then_triggers(self, evaluator, mock_execution_store, mock_composite_node, tz):
        """Test that condition triggers when exactly at interval (inclusive)"""
        # Arrange
        now = datetime.now(tz)
        last_execution = now - timedelta(hours=4.0)  # Exactly 4 hours

        mock_execution_store.get_last_execution.return_value = last_execution
        evaluator.set_evaluation_context("FREQ_STEPDOWN_4H", "TECO_VFD", "4")

        # Act
        result = evaluator._evaluate_time_elapsed_leaf(mock_composite_node)

        # Assert
        assert result is True

    # ========================================
    # Test: Just Before Interval
    # ========================================

    def test_when_just_before_interval_then_does_not_trigger(
        self, evaluator, mock_execution_store, mock_composite_node, tz
    ):
        """Test that condition does not trigger just before interval"""
        # Arrange
        now = datetime.now(tz)
        last_execution = now - timedelta(hours=3.99)  # Just under 4 hours

        mock_execution_store.get_last_execution.return_value = last_execution
        evaluator.set_evaluation_context("FREQ_STEPDOWN_4H", "TECO_VFD", "4")

        # Act
        result = evaluator._evaluate_time_elapsed_leaf(mock_composite_node)

        # Assert
        assert result is False

    # ========================================
    # Test: System Restart Persistence
    # ========================================

    def test_when_system_restarts_then_resumes_from_last_execution(
        self, evaluator, mock_execution_store, mock_composite_node, tz
    ):
        """Test that execution history survives system restart"""
        # Arrange: Simulate system restart
        # Last execution was 3 hours ago (persisted in DB)
        now = datetime.now(tz)
        last_execution = now - timedelta(hours=3)

        mock_execution_store.get_last_execution.return_value = last_execution
        evaluator.set_evaluation_context("FREQ_STEPDOWN_4H", "TECO_VFD", "4")

        # Act: System has restarted, evaluator is new but DB has history
        result = evaluator._evaluate_time_elapsed_leaf(mock_composite_node)

        # Assert: Should not trigger yet (only 3 hours elapsed)
        assert result is False
        mock_execution_store.get_last_execution.assert_called_once_with("FREQ_STEPDOWN_4H")

    # ========================================
    # Test: Multiple Rules Independence
    # ========================================

    def test_when_multiple_rules_then_tracked_independently(self, mock_execution_store, tz):
        """Test that different rules have independent execution tracking"""
        # Arrange
        evaluator = CompositeEvaluator(execution_store=mock_execution_store)

        now = datetime.now(tz)
        last_exec_rule1 = now - timedelta(hours=5)  # Rule 1: 5 hours ago (should trigger)
        last_exec_rule2 = now - timedelta(hours=2)  # Rule 2: 2 hours ago (should not trigger)

        def get_last_execution_side_effect(rule_code):
            if rule_code == "RULE_1":
                return last_exec_rule1
            elif rule_code == "RULE_2":
                return last_exec_rule2
            return None

        mock_execution_store.get_last_execution.side_effect = get_last_execution_side_effect

        node = Mock()
        node.type = ConditionType.TIME_ELAPSED
        node.interval_hours = 4.0

        # Act
        evaluator.set_evaluation_context("RULE_1", "TECO_VFD", "4")
        result1 = evaluator._evaluate_time_elapsed_leaf(node)

        evaluator.set_evaluation_context("RULE_2", "TECO_VFD", "4")
        result2 = evaluator._evaluate_time_elapsed_leaf(node)

        # Assert
        assert result1 is True  # Rule 1 should trigger
        assert result2 is False  # Rule 2 should not trigger

    # ========================================
    # Test: Error Handling
    # ========================================

    def test_when_execution_store_is_none_then_returns_false(self, mock_composite_node):
        """Test error handling when execution_store is not initialized"""
        # Arrange
        evaluator = CompositeEvaluator(execution_store=None)
        evaluator.set_evaluation_context("RULE_1", "TECO_VFD", "4")

        # Act
        result = evaluator._evaluate_time_elapsed_leaf(mock_composite_node)

        # Assert
        assert result is False

    def test_when_store_raises_exception_then_returns_false(self, evaluator, mock_execution_store, mock_composite_node):
        """Test error handling when database raises exception"""
        # Arrange
        mock_execution_store.get_last_execution.side_effect = Exception("DB connection error")
        evaluator.set_evaluation_context("RULE_1", "TECO_VFD", "4")

        # Act
        result = evaluator._evaluate_time_elapsed_leaf(mock_composite_node)

        # Assert
        assert result is False

    def test_when_invalid_interval_then_returns_false(self, evaluator, mock_execution_store):
        """Test error handling when interval_hours is invalid"""
        # Arrange
        node = Mock()
        node.type = ConditionType.TIME_ELAPSED
        node.interval_hours = -1.0  # Invalid: negative

        evaluator.set_evaluation_context("RULE_1", "TECO_VFD", "4")

        # Act
        result = evaluator._evaluate_time_elapsed_leaf(node)

        # Assert
        assert result is False

    # ========================================
    # Test: Different Intervals
    # ========================================

    @pytest.mark.parametrize(
        "interval_hours,elapsed_hours,expected_result",
        [
            (1.0, 0.5, False),  # Half hour elapsed, need 1 hour
            (1.0, 1.0, True),  # Exactly 1 hour
            (1.0, 1.5, True),  # Over 1 hour
            (0.5, 0.25, False),  # 15 minutes elapsed, need 30 minutes
            (0.5, 0.5, True),  # Exactly 30 minutes
            (12.0, 11.9, False),  # Just under 12 hours
            (12.0, 12.0, True),  # Exactly 12 hours
        ],
    )
    def test_various_intervals(
        self,
        mock_execution_store,
        tz,
        interval_hours,
        elapsed_hours,
        expected_result,
    ):
        """Test condition with various interval and elapsed combinations"""
        # Arrange
        evaluator = CompositeEvaluator(execution_store=mock_execution_store)
        evaluator.set_evaluation_context("TEST_RULE", "TECO_VFD", "4")

        node = Mock()
        node.type = ConditionType.TIME_ELAPSED
        node.interval_hours = interval_hours

        now = datetime.now(tz)
        last_execution = now - timedelta(hours=elapsed_hours)
        mock_execution_store.get_last_execution.return_value = last_execution

        # Act
        result = evaluator._evaluate_time_elapsed_leaf(node)

        # Assert
        assert result is expected_result


class TestTimeElapsedIntegrationWithCompositeNode:
    """Integration tests using real CompositeNode objects"""

    def test_when_evaluate_composite_node_with_time_elapsed_then_calls_evaluator(self):
        """Test that evaluate_composite_node dispatches to _evaluate_time_elapsed_leaf"""
        # Arrange

        mock_store = Mock()
        mock_store.get_last_execution.return_value = None

        evaluator = CompositeEvaluator(execution_store=mock_store)
        evaluator.set_evaluation_context("TEST_RULE", "TECO_VFD", "4")

        # Create real CompositeNode
        node = CompositeNode(type=ConditionType.TIME_ELAPSED, interval_hours=4.0)

        # Act
        result = evaluator.evaluate_composite_node(node, lambda x: None)

        # Assert
        assert result is True
        mock_store.get_last_execution.assert_called_once()
        mock_store.update_execution.assert_called_once()

    def test_when_build_reason_summary_with_time_elapsed_then_returns_correct_string(self):
        """Test that build_composite_reason_summary works for time_elapsed"""
        # Arrange

        evaluator = CompositeEvaluator()
        node = CompositeNode(type=ConditionType.TIME_ELAPSED, interval_hours=4.0)

        # Act
        reason = evaluator.build_composite_reason_summary(node)

        # Assert
        assert reason == "time_elapsed(interval=4.0h)"
