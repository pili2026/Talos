import pytest
import logging
from unittest.mock import Mock
from evaluator.control_evaluator import ControlEvaluator
from model.control_model import ControlActionModel, ControlConditionModel


class TestControlEvaluatorPriorityHandling:
    """Test priority-based condition selection in ControlEvaluator"""

    def test_when_multiple_conditions_match_then_selects_highest_priority(self, control_evaluator: ControlEvaluator):
        """Test that highest priority condition is selected when multiple conditions match"""
        # Arrange
        low_priority_condition = self._create_mock_condition("LOW_TEMP", "Low Temperature", 50)
        medium_priority_condition = self._create_mock_condition("MED_TEMP", "Medium Temperature", 70)
        high_priority_condition = self._create_mock_condition("HIGH_TEMP", "High Temperature", 90)

        conditions = [low_priority_condition, medium_priority_condition, high_priority_condition]
        control_evaluator.control_config.get_control_list.return_value = conditions

        # Mock composite evaluator to return True for all conditions (all match)
        control_evaluator.composite_evaluator.evaluate_composite_node.return_value = True
        control_evaluator.composite_evaluator.build_composite_reason_summary.return_value = "condition matched"

        snapshot = {"AIn01": 42.0}

        # Act
        result = control_evaluator.evaluate("TECO_VFD", "2", snapshot)

        # Assert
        assert len(result) == 1
        result_action = result[0]
        assert "HIGH_TEMP" in result_action.reason
        assert "priority=90" in result_action.reason

    def test_when_conditions_have_same_priority_then_selects_first_matching(self, control_evaluator: ControlEvaluator):
        """Test that first condition is selected when multiple conditions have the same priority"""
        # Arrange
        first_condition = self._create_mock_condition("COND_A", "Condition A", 80)
        second_condition = self._create_mock_condition("COND_B", "Condition B", 80)  # Same priority
        third_condition = self._create_mock_condition("COND_C", "Condition C", 80)  # Same priority

        conditions = [first_condition, second_condition, third_condition]
        control_evaluator.control_config.get_control_list.return_value = conditions

        # All conditions match
        control_evaluator.composite_evaluator.evaluate_composite_node.return_value = True
        control_evaluator.composite_evaluator.build_composite_reason_summary.return_value = "condition matched"

        snapshot = {"AIn01": 42.0}

        # Act
        result = control_evaluator.evaluate("TECO_VFD", "2", snapshot)

        # Assert: Should select the first condition with highest priority
        assert len(result) == 1
        result_action = result[0]
        assert "COND_A" in result_action.reason
        assert "priority=80" in result_action.reason

    def test_when_only_lower_priority_conditions_match_then_selects_highest_available(
        self, control_evaluator: ControlEvaluator
    ):
        """Test that highest available priority is selected when high priority conditions don't match"""
        # Arrange
        low_priority_condition = self._create_mock_condition("LOW_TEMP", "Low Temperature", 30)
        medium_priority_condition = self._create_mock_condition("MED_TEMP", "Medium Temperature", 60)
        high_priority_condition = self._create_mock_condition("HIGH_TEMP", "High Temperature", 90)

        conditions = [low_priority_condition, medium_priority_condition, high_priority_condition]
        control_evaluator.control_config.get_control_list.return_value = conditions

        # Mock composite evaluator - only low and medium priority match, high priority doesn't
        def mock_evaluate_composite(composite, get_value):
            # Determine which condition this is by checking the composite mock
            if composite == high_priority_condition.composite:
                return False  # High priority doesn't match
            else:
                return True  # Low and medium priority match

        control_evaluator.composite_evaluator.evaluate_composite_node.side_effect = mock_evaluate_composite
        control_evaluator.composite_evaluator.build_composite_reason_summary.return_value = "condition matched"

        snapshot = {"AIn01": 35.0}

        # Act
        result = control_evaluator.evaluate("TECO_VFD", "2", snapshot)

        # Assert: Should select medium priority (60) since high priority (90) doesn't match
        assert len(result) == 1
        result_action = result[0]
        assert "MED_TEMP" in result_action.reason
        assert "priority=60" in result_action.reason

    def test_when_priority_order_mixed_then_still_selects_highest(self, control_evaluator: ControlEvaluator):
        """Test that highest priority is selected regardless of order in condition list"""
        # Arrange - conditions in non-priority order
        high_priority_condition = self._create_mock_condition("HIGH_TEMP", "High Temperature", 95)
        low_priority_condition = self._create_mock_condition("LOW_TEMP", "Low Temperature", 10)
        medium_priority_condition = self._create_mock_condition("MED_TEMP", "Medium Temperature", 50)

        # Mix the order intentionally
        conditions = [medium_priority_condition, high_priority_condition, low_priority_condition]
        control_evaluator.control_config.get_control_list.return_value = conditions

        # All conditions match
        control_evaluator.composite_evaluator.evaluate_composite_node.return_value = True
        control_evaluator.composite_evaluator.build_composite_reason_summary.return_value = "condition matched"

        snapshot = {"AIn01": 42.0}

        # Act
        result = control_evaluator.evaluate("TECO_VFD", "2", snapshot)

        # Assert
        assert len(result) == 1
        result_action = result[0]
        assert "HIGH_TEMP" in result_action.reason
        assert "priority=95" in result_action.reason

    def test_when_no_conditions_match_then_returns_empty_list(self, control_evaluator: ControlEvaluator):
        """Test that empty list is returned when no conditions match composite evaluation"""
        # Arrange
        condition1 = self._create_mock_condition("COND1", "Condition 1", 70)
        condition2 = self._create_mock_condition("COND2", "Condition 2", 80)

        conditions = [condition1, condition2]
        control_evaluator.control_config.get_control_list.return_value = conditions

        # No conditions match
        control_evaluator.composite_evaluator.evaluate_composite_node.return_value = False

        snapshot = {"AIn01": 20.0}

        # Act
        result = control_evaluator.evaluate("TECO_VFD", "2", snapshot)

        # Assert
        assert len(result) == 0

    def test_when_condition_has_invalid_composite_then_skips_condition(self, control_evaluator: ControlEvaluator):
        """Test that conditions with invalid composite are skipped"""
        # Arrange
        valid_condition = self._create_mock_condition("VALID", "Valid Condition", 70)
        invalid_condition = self._create_mock_condition("INVALID", "Invalid Condition", 90)

        # Make invalid_condition have invalid composite
        invalid_condition.composite.invalid = True

        conditions = [invalid_condition, valid_condition]  # Invalid has higher priority
        control_evaluator.control_config.get_control_list.return_value = conditions

        # Only valid condition should be evaluated
        control_evaluator.composite_evaluator.evaluate_composite_node.return_value = True
        control_evaluator.composite_evaluator.build_composite_reason_summary.return_value = "condition matched"

        snapshot = {"AIn01": 42.0}

        # Act
        result = control_evaluator.evaluate("TECO_VFD", "2", snapshot)

        # Assert: Should select valid condition even though invalid has higher priority
        assert len(result) == 1
        result_action = result[0]
        assert "VALID" in result_action.reason
        assert "priority=70" in result_action.reason

    def test_when_condition_has_none_composite_then_skips_condition(self, control_evaluator: ControlEvaluator):
        """Test that conditions with None composite are skipped"""
        # Arrange
        valid_condition = self._create_mock_condition("VALID", "Valid Condition", 70)
        none_composite_condition = self._create_mock_condition("NONE_COMP", "None Composite", 90)

        # Make condition have None composite
        none_composite_condition.composite = None

        conditions = [none_composite_condition, valid_condition]
        control_evaluator.control_config.get_control_list.return_value = conditions

        control_evaluator.composite_evaluator.evaluate_composite_node.return_value = True
        control_evaluator.composite_evaluator.build_composite_reason_summary.return_value = "condition matched"

        snapshot = {"AIn01": 42.0}

        # Act
        result = control_evaluator.evaluate("TECO_VFD", "2", snapshot)

        # Assert
        assert len(result) == 1
        result_action = result[0]
        assert "VALID" in result_action.reason

    def test_when_selected_condition_has_missing_action_fields_then_returns_empty_list(
        self, control_evaluator: ControlEvaluator, caplog
    ):
        """Test that conditions with missing action model/slave_id are skipped"""
        # Arrange
        caplog.set_level(logging.WARNING)

        condition = self._create_mock_condition("TEST", "Test Condition", 80)
        # Make action missing required fields
        condition.action.model = ""  # Missing model
        condition.action.slave_id = ""  # Missing slave_id

        conditions = [condition]
        control_evaluator.control_config.get_control_list.return_value = conditions

        control_evaluator.composite_evaluator.evaluate_composite_node.return_value = True

        snapshot = {"AIn01": 42.0}

        # Act
        result = control_evaluator.evaluate("TECO_VFD", "2", snapshot)

        # Assert
        assert len(result) == 0
        assert "missing action fields" in caplog.text

    def test_when_policy_processing_fails_then_returns_empty_list(self, control_evaluator: ControlEvaluator, caplog):
        """Test that conditions with policy processing failure return empty list"""
        # Arrange
        caplog.set_level(logging.WARNING)

        condition = self._create_mock_condition("TEST", "Test Condition", 80)

        conditions = [condition]
        control_evaluator.control_config.get_control_list.return_value = conditions

        control_evaluator.composite_evaluator.evaluate_composite_node.return_value = True

        # Mock _apply_policy_to_action to return None (processing failure)
        control_evaluator._apply_policy_to_action = Mock(return_value=None)

        snapshot = {"AIn01": 42.0}

        # Act
        result = control_evaluator.evaluate("TECO_VFD", "2", snapshot)

        # Assert
        assert len(result) == 0
        assert "policy processing failure" in caplog.text

    def test_when_mixed_matching_and_non_matching_conditions_then_selects_highest_matching(
        self, control_evaluator: ControlEvaluator
    ):
        """Test complex scenario with mix of matching/non-matching conditions at different priorities"""
        # Arrange
        non_matching_high = self._create_mock_condition("HIGH_NO_MATCH", "High No Match", 100)
        matching_medium = self._create_mock_condition("MED_MATCH", "Medium Match", 60)
        non_matching_medium = self._create_mock_condition("MED_NO_MATCH", "Medium No Match", 65)
        matching_low = self._create_mock_condition("LOW_MATCH", "Low Match", 20)

        conditions = [non_matching_high, matching_medium, non_matching_medium, matching_low]
        control_evaluator.control_config.get_control_list.return_value = conditions

        # Setup complex matching pattern
        def mock_evaluate_composite(composite, get_value):
            if composite == non_matching_high.composite or composite == non_matching_medium.composite:
                return False
            else:
                return True  # matching_medium and matching_low match

        control_evaluator.composite_evaluator.evaluate_composite_node.side_effect = mock_evaluate_composite
        control_evaluator.composite_evaluator.build_composite_reason_summary.return_value = "condition matched"

        snapshot = {"AIn01": 35.0}

        # Act
        result = control_evaluator.evaluate("TECO_VFD", "2", snapshot)

        # Assert: Should select matching_medium (priority 60) since higher priorities don't match
        assert len(result) == 1
        result_action = result[0]
        assert "MED_MATCH" in result_action.reason
        assert "priority=60" in result_action.reason

    # Helper method to create mock conditions
    def _create_mock_condition(self, code: str, name: str, priority: int) -> Mock:
        """Create a mock condition with basic setup"""
        condition = Mock(spec=ControlConditionModel)
        condition.code = code
        condition.name = name
        condition.priority = priority

        # Mock composite
        condition.composite = Mock()
        condition.composite.invalid = False

        # Mock policy
        condition.policy = Mock()
        condition.policy.type = "discrete_setpoint"

        # Mock action
        condition.action = Mock(spec=ControlActionModel)
        condition.action.model = "TECO_VFD"
        condition.action.slave_id = "2"
        condition.action.type = "set_frequency"
        condition.action.target = "RW_HZ"
        condition.action.value = 50.0
        condition.action.model_copy.return_value = condition.action  # Return self for simplicity

        return condition


class TestControlEvaluatorMultiConditionEdgeCases:
    """Test edge cases in multi-condition evaluation"""

    def test_when_empty_condition_list_then_returns_empty_list(self, control_evaluator: ControlEvaluator):
        """Test that empty list is returned when no conditions are configured"""
        # Arrange
        control_evaluator.control_config.get_control_list.return_value = []

        snapshot = {"AIn01": 42.0}

        # Act
        result = control_evaluator.evaluate("TECO_VFD", "2", snapshot)

        # Assert
        assert len(result) == 0

    def test_when_all_conditions_have_invalid_composite_then_returns_empty_list(
        self, control_evaluator: ControlEvaluator
    ):
        """Test that empty list is returned when all conditions have invalid composite"""
        # Arrange
        condition1 = Mock(spec=ControlConditionModel)
        condition1.composite = Mock()
        condition1.composite.invalid = True

        condition2 = Mock(spec=ControlConditionModel)
        condition2.composite = None

        conditions = [condition1, condition2]
        control_evaluator.control_config.get_control_list.return_value = conditions

        snapshot = {"AIn01": 42.0}

        # Act
        result = control_evaluator.evaluate("TECO_VFD", "2", snapshot)

        # Assert
        assert len(result) == 0

    def test_when_single_condition_matches_then_returns_that_condition(self, control_evaluator: ControlEvaluator):
        """Test that single matching condition is returned correctly"""
        # Arrange
        condition = Mock(spec=ControlConditionModel)
        condition.code = "SINGLE"
        condition.name = "Single Condition"
        condition.priority = 75
        condition.composite = Mock()
        condition.composite.invalid = False
        condition.policy = Mock()
        condition.policy.type = "discrete_setpoint"

        condition.action = Mock(spec=ControlActionModel)
        condition.action.model = "TECO_VFD"
        condition.action.slave_id = "2"
        condition.action.type = "set_frequency"
        condition.action.target = "RW_HZ"
        condition.action.value = 50.0
        condition.action.model_copy.return_value = condition.action

        conditions = [condition]
        control_evaluator.control_config.get_control_list.return_value = conditions

        control_evaluator.composite_evaluator.evaluate_composite_node.return_value = True
        control_evaluator.composite_evaluator.build_composite_reason_summary.return_value = "single condition"

        snapshot = {"AIn01": 42.0}

        # Act
        result = control_evaluator.evaluate("TECO_VFD", "2", snapshot)

        # Assert
        assert len(result) == 1
        result_action = result[0]
        assert "SINGLE" in result_action.reason
        assert "priority=75" in result_action.reason

    def test_when_priority_is_none_then_handles_gracefully(self, control_evaluator: ControlEvaluator):
        """Test that conditions with None priority are handled correctly"""
        # Arrange
        none_priority_condition = Mock(spec=ControlConditionModel)
        none_priority_condition.code = "NONE_PRI"
        none_priority_condition.name = "None Priority"
        none_priority_condition.priority = None  # None priority
        none_priority_condition.composite = Mock()
        none_priority_condition.composite.invalid = False
        none_priority_condition.policy = Mock()
        none_priority_condition.policy.type = "discrete_setpoint"

        none_priority_condition.action = Mock(spec=ControlActionModel)
        none_priority_condition.action.model = "TECO_VFD"
        none_priority_condition.action.slave_id = "2"
        none_priority_condition.action.type = "set_frequency"
        none_priority_condition.action.value = 30.0
        none_priority_condition.action.model_copy.return_value = none_priority_condition.action

        normal_condition = Mock(spec=ControlConditionModel)
        normal_condition.code = "NORMAL"
        normal_condition.name = "Normal Condition"
        normal_condition.priority = 50
        normal_condition.composite = Mock()
        normal_condition.composite.invalid = False
        normal_condition.policy = Mock()
        normal_condition.policy.type = "discrete_setpoint"

        normal_condition.action = Mock(spec=ControlActionModel)
        normal_condition.action.model = "TECO_VFD"
        normal_condition.action.slave_id = "2"
        normal_condition.action.type = "set_frequency"
        normal_condition.action.value = 40.0
        normal_condition.action.model_copy.return_value = normal_condition.action

        conditions = [none_priority_condition, normal_condition]
        control_evaluator.control_config.get_control_list.return_value = conditions

        control_evaluator.composite_evaluator.evaluate_composite_node.return_value = True
        control_evaluator.composite_evaluator.build_composite_reason_summary.return_value = "condition matched"

        snapshot = {"AIn01": 42.0}

        # Act
        result = control_evaluator.evaluate("TECO_VFD", "2", snapshot)

        # Assert: Should select the condition with numeric priority (50) over None priority
        assert len(result) == 1
        result_action = result[0]
        assert "NORMAL" in result_action.reason
        assert "priority=50" in result_action.reason
