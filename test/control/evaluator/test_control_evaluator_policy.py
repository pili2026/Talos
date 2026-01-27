import logging
from unittest.mock import Mock

import pytest

from core.evaluator.control_evaluator import ControlEvaluator
from core.model.control_composite import CompositeNode
from core.model.enum.condition_enum import ConditionOperator, ConditionType, ControlActionType, ControlPolicyType
from core.schema.constraint_schema import ConstraintConfigSchema
from core.schema.control_condition_schema import ConditionSchema, ControlActionSchema
from core.schema.control_condition_source_schema import Source
from core.schema.control_config_schema import ControlConfig


class TestControlEvaluatorPolicyProcessing:
    """
    Test policy processing logic in ControlEvaluator
    Tests three policy types: discrete_setpoint, absolute_linear, incremental_linear
    """

    @pytest.fixture
    def constraint_config_schema(self):
        return ConstraintConfigSchema(
            **{
                "LITEON_EVO6800": {
                    "default_constraints": {"RW_HZ": {"min": 30, "max": 55}},
                    "instances": {
                        "1": {"constraints": {"RW_HZ": {"min": 55, "max": 57}}},
                        "2": {"use_default_constraints": True},
                    },
                }
            }
        )

    @pytest.fixture
    def mock_control_config(self):
        """Create mock ControlConfig for testing"""
        config = Mock(spec=ControlConfig)
        return config

    @pytest.fixture
    def control_evaluator(self, mock_control_config, constraint_config_schema):
        return ControlEvaluator(mock_control_config, constraint_config_schema)

    def test_when_discrete_setpoint_policy_then_returns_original_fixed_value(self, control_evaluator):
        """Test that discrete_setpoint policy returns the original fixed value from YAML"""
        # Arrange
        mock_condition = Mock(spec=ConditionSchema)
        mock_condition.code = "HIGH_TEMP"
        mock_condition.name = "High Temperature Shutdown"
        mock_condition.priority = 80

        # discrete_setpoint policy
        mock_policy = Mock()
        mock_policy.configure_mock(**{"type": "discrete_setpoint"})
        mock_condition.policy = mock_policy

        # action with fixed value
        mock_action = Mock(spec=ControlActionSchema)
        mock_action.model = "TECO_VFD"
        mock_action.slave_id = "2"
        mock_action.type = "set_frequency"
        mock_action.target = "RW_HZ"
        mock_action.value = 45.0  # Fixed value from YAML
        mock_condition.action = mock_action

        snapshot = {"AIn01": 42.0}  # Above threshold

        # Act
        result_action = control_evaluator._apply_policy_to_action(mock_condition, mock_action, snapshot)

        # Assert
        assert result_action is mock_action  # Should return original action unchanged
        assert result_action.type == "set_frequency"
        assert result_action.value == 45.0  # Should keep original fixed value

    def test_when_absolute_linear_then_calculates_absolute_frequency(self, control_evaluator):
        """Test absolute_linear policy calculates frequency"""

        real_source = Source(device="SD400", slave_id="1", pins=["AIn01"])

        real_composite = CompositeNode(
            sources_id="cond_0",
            type=ConditionType.THRESHOLD,
            sources=[real_source],
            operator=ConditionOperator.GREATER_THAN,
            threshold=25.0,
        )

        mock_policy = Mock()
        mock_policy.type = ControlPolicyType.ABSOLUTE_LINEAR
        mock_policy.input_sources_id = "cond_0"
        mock_policy.base_freq = 40.0
        mock_policy.base_temp = 25.0
        mock_policy.gain_hz_per_unit = 1.2

        # Mock condition
        mock_condition = Mock()
        mock_condition.composite = real_composite
        mock_condition.policy = mock_policy

        # Mock action
        mock_action = Mock()
        mock_action.model_copy = Mock(return_value=Mock())

        # Snapshot
        snapshot = {"AIn01": 29.0}

        # Act
        result = control_evaluator._apply_policy_to_action(mock_condition, mock_action, snapshot)

        # Assert
        assert result is not None
        assert result.value == 44.8

    def test_when_absolute_linear_at_base_temp_then_uses_base_frequency(self, control_evaluator):
        """Test absolute_linear uses base frequency when temp equals base_temp"""

        real_source = Source(device="SD400", slave_id="1", pins=["AIn01"])
        real_composite = CompositeNode(
            sources_id="cond_0",
            type=ConditionType.THRESHOLD,
            sources=[real_source],
            operator=ConditionOperator.GREATER_THAN,
            threshold=25.0,
        )

        # Mock policy
        mock_policy = Mock()
        mock_policy.type = ControlPolicyType.ABSOLUTE_LINEAR
        mock_policy.input_sources_id = "cond_0"
        mock_policy.base_freq = 40.0
        mock_policy.base_temp = 25.0
        mock_policy.gain_hz_per_unit = 1.2

        # Mock condition
        mock_condition = Mock()
        mock_condition.composite = real_composite
        mock_condition.policy = mock_policy

        # Mock action
        mock_action = Mock()
        mock_action.model_copy = Mock(return_value=Mock())

        # Temperature equals base_temp: 25°C
        snapshot = {"AIn01": 25.0}

        # Act
        result = control_evaluator._apply_policy_to_action(mock_condition, mock_action, snapshot)

        # Assert
        # Expected: 40.0 + (25.0 - 25.0) * 1.2 = 40.0
        assert result is not None
        assert result.value == 40.0
        assert result.type == ControlActionType.SET_FREQUENCY

    def test_when_incremental_linear_then_calculates_adjustment(self, control_evaluator):
        """Test incremental_linear calculates frequency adjustment"""

        real_sources = [
            Source(device="SD400", slave_id="1", pins=["AIn01"]),
            Source(device="SD400", slave_id="1", pins=["AIn02"]),
        ]
        real_composite = CompositeNode(
            sources_id="cond_0",
            type=ConditionType.DIFFERENCE,
            sources=real_sources,
            operator=ConditionOperator.GREATER_THAN,
            threshold=4.0,
        )

        mock_policy = Mock()
        mock_policy.type = ControlPolicyType.INCREMENTAL_LINEAR
        mock_policy.input_sources_id = "cond_0"
        mock_policy.gain_hz_per_unit = 1.5

        mock_condition = Mock()
        mock_condition.composite = real_composite
        mock_condition.policy = mock_policy

        mock_action = Mock()
        mock_action.model_copy = Mock(return_value=Mock())

        # Temperature difference: 27 - 20 = 7°C
        snapshot = {"AIn01": 27.0, "AIn02": 20.0}

        # Act
        result = control_evaluator._apply_policy_to_action(mock_condition, mock_action, snapshot)

        # Assert
        assert result is not None
        assert result.type == ControlActionType.ADJUST_FREQUENCY
        assert result.value == 1.5

    def test_when_incremental_linear_negative_diff_then_calculates_negative_adjustment(self, control_evaluator):
        """Test incremental_linear calculates negative adjustment"""

        real_sources = [
            Source(device="SD400", slave_id="1", pins=["AIn01"]),
            Source(device="SD400", slave_id="1", pins=["AIn02"]),
        ]
        real_composite = CompositeNode(
            sources_id="cond_0",
            type=ConditionType.DIFFERENCE,
            sources=real_sources,
            operator=ConditionOperator.GREATER_THAN,
            threshold=4.0,
        )

        mock_policy = Mock()
        mock_policy.type = ControlPolicyType.INCREMENTAL_LINEAR
        mock_policy.input_sources_id = "cond_0"
        mock_policy.gain_hz_per_unit = -1.5

        mock_condition = Mock()
        mock_condition.composite = real_composite
        mock_condition.policy = mock_policy

        mock_action = Mock()
        mock_action.model_copy = Mock(return_value=Mock())

        # Negative difference: 18 - 25 = -7°C
        snapshot = {"AIn01": 18.0, "AIn02": 25.0}

        # Act
        result = control_evaluator._apply_policy_to_action(mock_condition, mock_action, snapshot)

        # Assert
        assert result is not None
        assert result.type == ControlActionType.ADJUST_FREQUENCY
        assert result.value == -1.5

    def test_when_no_policy_exists_then_returns_original_action(self, control_evaluator):
        """Test that original action is returned when no policy is defined"""
        # Arrange
        mock_condition = Mock(spec=ConditionSchema)
        mock_condition.policy = None

        mock_action = Mock(spec=ControlActionSchema)
        snapshot = {}

        # Act
        result_action = control_evaluator._apply_policy_to_action(mock_condition, mock_action, snapshot)

        # Assert
        assert result_action is mock_action  # Should return original action unchanged

    def test_when_policy_type_is_unknown_then_returns_original_action(self, control_evaluator, caplog):
        """Test that original action is returned when policy type is unknown"""
        # Arrange
        caplog.set_level(logging.WARNING)
        mock_condition = Mock(spec=ConditionSchema)
        mock_policy = Mock()
        mock_policy.configure_mock(**{"type": "unknown_policy_type"})
        mock_condition.policy = mock_policy

        mock_action = Mock(spec=ControlActionSchema)
        snapshot = {}

        # Act
        result_action = control_evaluator._apply_policy_to_action(mock_condition, mock_action, snapshot)

        # Assert
        assert result_action is mock_action
        assert "Unsupported policy type" in caplog.text


class TestControlEvaluatorIntegration:
    """Integration tests for complete evaluation flow"""

    @pytest.fixture
    def constraint_config_schema(self):
        return ConstraintConfigSchema(
            **{
                "LITEON_EVO6800": {
                    "default_constraints": {"RW_HZ": {"min": 30, "max": 55}},
                    "instances": {
                        "1": {"constraints": {"RW_HZ": {"min": 55, "max": 57}}},
                        "2": {"use_default_constraints": True},
                    },
                }
            }
        )

    @pytest.fixture
    def mock_control_config(self):
        """Create mock ControlConfig for testing"""
        config = Mock(spec=ControlConfig)
        return config

    @pytest.fixture
    def control_evaluator(self, mock_control_config, constraint_config_schema):
        """Create ControlEvaluator with mocked dependencies"""
        evaluator = ControlEvaluator(mock_control_config, constraint_config_schema)
        evaluator.composite_evaluator = Mock()
        return evaluator

    def test_when_condition_matches_and_has_absolute_linear_policy_then_returns_calculated_action(
        self, control_evaluator, caplog
    ):
        caplog.set_level(logging.DEBUG)

        real_source = Source(device="TECO_VFD", slave_id="2", pins=["AIn01"])
        real_composite = CompositeNode(
            sources_id="cond_0",
            type=ConditionType.THRESHOLD,
            sources=[real_source],
            operator=ConditionOperator.GREATER_THAN,
            threshold=25.0,
        )

        # Mock policy
        mock_policy = Mock()
        mock_policy.type = ControlPolicyType.ABSOLUTE_LINEAR
        mock_policy.input_sources_id = "cond_0"
        mock_policy.base_freq = 40.0
        mock_policy.base_temp = 25.0
        mock_policy.gain_hz_per_unit = 1.2

        # Mock action
        mock_action = Mock(spec=ControlActionSchema)
        mock_action.model = "TECO_VFD"
        mock_action.slave_id = "2"
        mock_action.type = ControlActionType.SET_FREQUENCY
        mock_action.target = "RW_HZ"
        mock_action.value = None
        mock_action.emergency_override = False
        mock_action.model_copy = Mock(return_value=Mock())

        # Mock condition
        mock_condition = Mock(spec=ConditionSchema)
        mock_condition.code = "ABS_TEMP01"
        mock_condition.name = "Environment Temperature Linear Control"
        mock_condition.priority = 90
        mock_condition.blocking = False
        mock_condition.active_time_ranges = None
        mock_condition.composite = real_composite
        mock_condition.policy = mock_policy
        mock_condition.actions = [mock_action]

        # Mock composite evaluator
        control_evaluator.composite_evaluator.evaluate_composite_node.return_value = True
        control_evaluator.composite_evaluator.build_composite_reason_summary.return_value = "threshold(AIn01 gt 25.0)"

        # Mock control_config
        control_evaluator.control_config.get_control_list.return_value = [mock_condition]

        # Snapshot
        snapshot = {"AIn01": 29.0}

        # Act
        result = control_evaluator.evaluate("TECO_VFD", "2", snapshot)

        # Assert
        assert len(result) == 1
        action = result[0]

        # Expected: 40.0 + (29.0 - 25.0) * 1.2 = 44.8
        expected_freq = 40.0 + (29.0 - 25.0) * 1.2
        assert action.value == expected_freq
        assert action.type == ControlActionType.SET_FREQUENCY

    def test_when_no_conditions_match_then_returns_empty_list(self, control_evaluator):
        """Test that empty list is returned when no conditions match"""
        # Arrange
        mock_condition = Mock(spec=ConditionSchema)
        mock_composite = Mock()
        mock_condition.composite = mock_composite

        # Composite evaluation returns False (condition doesn't match)
        control_evaluator.composite_evaluator.evaluate_composite_node.return_value = False

        control_evaluator.control_config.get_control_list.return_value = [mock_condition]

        snapshot = {"AIn01": 20.0, "AIn02": 20.0}

        # Act
        result = control_evaluator.evaluate("TECO_VFD", "2", snapshot)

        # Assert
        assert len(result) == 0
