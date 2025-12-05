import logging
from unittest.mock import Mock

from core.evaluator.control_evaluator import ControlEvaluator
from core.model.enum.condition_enum import ControlActionType, ControlPolicyType
from core.schema.control_condition_schema import ConditionSchema, ControlActionSchema


class TestControlEvaluatorPriorityHandling:
    """Test priority-based condition selection in ControlEvaluator"""

    def test_when_multiple_conditions_match_then_executes_all_in_priority_order(
        self, control_evaluator: ControlEvaluator
    ):
        """Test that all matching conditions are executed in priority order (cumulative mode)"""
        # Arrange
        low_priority_condition = self._create_mock_condition("LOW_TEMP", "Low Temperature", 90)
        medium_priority_condition = self._create_mock_condition("MED_TEMP", "Medium Temperature", 70)
        high_priority_condition = self._create_mock_condition("HIGH_TEMP", "High Temperature", 50)

        conditions = [low_priority_condition, medium_priority_condition, high_priority_condition]
        control_evaluator.control_config.get_control_list.return_value = conditions

        # Mock composite evaluator to return True for all conditions (all match)
        control_evaluator.composite_evaluator.evaluate_composite_node.return_value = True
        control_evaluator.composite_evaluator.build_composite_reason_summary.return_value = "condition matched"

        snapshot = {"AIn01": 42.0}

        # Act
        result = control_evaluator.evaluate("TECO_VFD", "2", snapshot)

        # Assert - All 3 conditions should produce actions (cumulative mode)
        assert len(result) == 3

        # Check priority order
        assert "HIGH_TEMP" in result[0].reason
        assert "priority=50" in result[0].reason
        assert "MED_TEMP" in result[1].reason
        assert "priority=70" in result[1].reason
        assert "LOW_TEMP" in result[2].reason
        assert "priority=90" in result[2].reason

    def test_when_conditions_have_same_priority_then_executes_in_definition_order(
        self, control_evaluator: ControlEvaluator
    ):
        """Test that conditions with same priority execute in definition order"""
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

        # Assert: Should execute all 3 conditions in order
        assert len(result) == 3
        assert "COND_A" in result[0].reason
        assert "COND_B" in result[1].reason
        assert "COND_C" in result[2].reason

    def test_when_only_some_conditions_match_then_executes_only_matching(self, control_evaluator: ControlEvaluator):
        """Test that only matching conditions produce actions"""
        # Arrange
        low_priority_condition = self._create_mock_condition("LOW_TEMP", "Low Temperature", 90)
        medium_priority_condition = self._create_mock_condition("MED_TEMP", "Medium Temperature", 60)
        high_priority_condition = self._create_mock_condition("HIGH_TEMP", "High Temperature", 30)

        conditions = [low_priority_condition, medium_priority_condition, high_priority_condition]
        control_evaluator.control_config.get_control_list.return_value = conditions

        # Mock composite evaluator - only low and medium priority match
        def mock_evaluate_composite(composite, get_value):
            if composite == high_priority_condition.composite:
                return False  # High priority doesn't match
            else:
                return True  # Low and medium priority match

        control_evaluator.composite_evaluator.evaluate_composite_node.side_effect = mock_evaluate_composite
        control_evaluator.composite_evaluator.build_composite_reason_summary.return_value = "condition matched"

        snapshot = {"AIn01": 35.0}

        # Act
        result = control_evaluator.evaluate("TECO_VFD", "2", snapshot)

        # Assert: Should have 2 actions (medium and low priority)
        assert len(result) == 2
        assert "MED_TEMP" in result[0].reason
        assert "priority=60" in result[0].reason
        assert "LOW_TEMP" in result[1].reason
        assert "priority=90" in result[1].reason

    def test_when_priority_order_mixed_then_sorts_by_priority(self, control_evaluator: ControlEvaluator):
        """Test that conditions are sorted by priority regardless of definition order"""
        # Arrange - conditions in non-priority order
        high_priority_condition = self._create_mock_condition("HIGH_TEMP", "High Temperature", 10)
        low_priority_condition = self._create_mock_condition("LOW_TEMP", "Low Temperature", 95)
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

        # Assert - Should execute in priority order (10, 50, 95)
        assert len(result) == 3
        assert "HIGH_TEMP" in result[0].reason
        assert "priority=10" in result[0].reason
        assert "MED_TEMP" in result[1].reason
        assert "priority=50" in result[1].reason
        assert "LOW_TEMP" in result[2].reason
        assert "priority=95" in result[2].reason

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

        # Assert: Should execute valid condition
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

    def test_when_selected_condition_has_missing_action_fields_then_skips_action(
        self, control_evaluator: ControlEvaluator, caplog
    ):
        """Test that actions with missing model/slave_id are skipped"""
        # Arrange
        caplog.set_level(logging.WARNING)

        condition = self._create_mock_condition("TEST", "Test Condition", 80)
        # Make action missing required fields
        condition.actions[0].model = ""  # ← 改成 actions[0]
        condition.actions[0].slave_id = ""  # ← 改成 actions[0]

        conditions = [condition]
        control_evaluator.control_config.get_control_list.return_value = conditions

        control_evaluator.composite_evaluator.evaluate_composite_node.return_value = True

        snapshot = {"AIn01": 42.0}

        # Act
        result = control_evaluator.evaluate("TECO_VFD", "2", snapshot)

        # Assert
        assert len(result) == 0
        assert "missing action fields" in caplog.text

    def test_when_policy_processing_fails_then_skips_action(self, control_evaluator: ControlEvaluator, caplog):
        """Test that actions with policy processing failure are skipped"""
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

    def test_when_mixed_matching_and_non_matching_conditions_then_executes_only_matching(
        self, control_evaluator: ControlEvaluator
    ):
        """Test complex scenario with mix of matching/non-matching conditions"""
        # Arrange
        non_matching_high = self._create_mock_condition("HIGH_NO_MATCH", "High No Match", 10)
        matching_medium = self._create_mock_condition("MED_MATCH", "Medium Match", 65)
        non_matching_medium = self._create_mock_condition("MED_NO_MATCH", "Medium No Match", 60)
        matching_low = self._create_mock_condition("LOW_MATCH", "Low Match", 100)

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

        # Assert: Should execute 2 actions (matching_medium and matching_low)
        assert len(result) == 2
        assert "MED_MATCH" in result[0].reason
        assert "priority=65" in result[0].reason
        assert "LOW_MATCH" in result[1].reason
        assert "priority=100" in result[1].reason

    # Helper method to create mock conditions
    def _create_mock_condition(self, code: str, name: str, priority: int) -> Mock:
        """Create a mock condition with basic setup"""
        condition = Mock(spec=ConditionSchema)
        condition.code = code
        condition.name = name
        condition.priority = priority
        condition.blocking = False  # ← 新增 blocking 欄位

        # Mock composite
        condition.composite = Mock()
        condition.composite.invalid = False

        # Mock policy
        condition.policy = Mock()
        condition.policy.type = ControlPolicyType.DISCRETE_SETPOINT

        mock_action = Mock(spec=ControlActionSchema)
        mock_action.model = "TECO_VFD"
        mock_action.slave_id = "2"
        mock_action.type = ControlActionType.SET_FREQUENCY
        mock_action.target = "RW_HZ"
        mock_action.value = 50.0
        mock_action.emergency_override = False
        mock_action.model_copy.return_value = mock_action  # Return self for simplicity

        condition.actions = [mock_action]  # ← 改成 list

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
        condition1 = Mock(spec=ConditionSchema)
        condition1.composite = Mock()
        condition1.composite.invalid = True

        condition2 = Mock(spec=ConditionSchema)
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
        condition = Mock(spec=ConditionSchema)
        condition.code = "Threshold"
        condition.name = "Single Condition"
        condition.priority = 75
        condition.blocking = False
        condition.composite = Mock()
        condition.composite.invalid = False
        condition.policy = Mock()
        condition.policy.type = ControlPolicyType.DISCRETE_SETPOINT

        mock_action = Mock(spec=ControlActionSchema)
        mock_action.model = "TECO_VFD"
        mock_action.slave_id = "2"
        mock_action.type = ControlActionType.SET_FREQUENCY
        mock_action.target = "RW_HZ"
        mock_action.value = 50.0
        mock_action.emergency_override = False
        mock_action.model_copy.return_value = mock_action

        condition.actions = [mock_action]

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
        assert "Threshold" in result_action.reason
        assert "priority=75" in result_action.reason

    def test_when_priority_is_none_then_handles_gracefully(self, control_evaluator: ControlEvaluator):
        """Test that conditions with None priority are handled correctly"""
        # Arrange
        none_priority_condition = Mock(spec=ConditionSchema)
        none_priority_condition.code = "NONE_PRI"
        none_priority_condition.name = "None Priority"
        none_priority_condition.priority = None  # None priority
        none_priority_condition.blocking = False
        none_priority_condition.composite = Mock()
        none_priority_condition.composite.invalid = False
        none_priority_condition.policy = Mock()
        none_priority_condition.policy.type = ControlPolicyType.DISCRETE_SETPOINT

        mock_action1 = Mock(
            spec_set=[
                "model",
                "slave_id",
                "type",
                "value",
                "emergency_override",
                "model_copy",
                "target",
                "priority",
                "reason",
            ]
        )

        mock_action1.model = "TECO_VFD"
        mock_action1.slave_id = "2"
        mock_action1.type = ControlActionType.SET_FREQUENCY
        mock_action1.value = 30.0
        mock_action1.emergency_override = False
        mock_action1.target = "RW_HZ"
        mock_action1.model_copy.return_value = mock_action1

        none_priority_condition.actions = [mock_action1]

        normal_condition = Mock(spec=ConditionSchema)
        normal_condition.code = "NORMAL"
        normal_condition.name = "Normal Condition"
        normal_condition.priority = 50
        normal_condition.blocking = False
        normal_condition.composite = Mock()
        normal_condition.composite.invalid = False
        normal_condition.policy = Mock()
        normal_condition.policy.type = ControlPolicyType.DISCRETE_SETPOINT

        mock_action2 = Mock(
            spec_set=[
                "model",
                "slave_id",
                "type",
                "value",
                "emergency_override",
                "model_copy",
                "target",
                "priority",
                "reason",
            ]
        )

        mock_action2.model = "TECO_VFD"
        mock_action2.slave_id = "2"
        mock_action2.type = ControlActionType.SET_FREQUENCY
        mock_action2.value = 40.0
        mock_action2.emergency_override = False
        mock_action2.target = "RW_HZ"
        mock_action2.model_copy.return_value = mock_action2

        normal_condition.actions = [mock_action2]

        conditions = [none_priority_condition, normal_condition]
        control_evaluator.control_config.get_control_list.return_value = conditions

        control_evaluator.composite_evaluator.evaluate_composite_node.return_value = True
        control_evaluator.composite_evaluator.build_composite_reason_summary.return_value = "condition matched"

        snapshot = {"AIn01": 42.0}

        # Act
        result = control_evaluator.evaluate("TECO_VFD", "2", snapshot)

        # Assert: Should execute both (cumulative mode)
        # None priority will be treated as 0 (highest) in sorting
        assert len(result) == 2
