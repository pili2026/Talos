import pytest
import logging
from unittest.mock import Mock
from schema.control_condition_schema import ControlActionSchema, ConditionSchema
from model.enum.condition_enum import ControlActionType
from schema.constraint_schema import ConstraintConfigSchema
from schema.control_config_schema import ControlConfig
from evaluator.control_evaluator import ControlEvaluator


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
        """Test that absolute_linear policy calculates absolute frequency based on single temperature"""
        # Arrange
        mock_condition = Mock(spec=ConditionSchema)
        mock_condition.code = "ABS_TEMP01"

        # absolute_linear policy with correct configuration
        mock_policy = Mock()
        mock_policy.configure_mock(
            **{
                "type": "absolute_linear",
                "condition_type": "threshold",
                "sources": ["AIn01"],
                "base_freq": 40.0,
                "base_temp": 25.0,
                "gain_hz_per_unit": 1.2,
            }
        )
        mock_condition.policy = mock_policy

        mock_action = Mock(spec=ControlActionSchema)
        mock_action.model = "TECO_VFD"
        mock_action.slave_id = "2"
        mock_action.type = "set_frequency"
        mock_action.target = "RW_HZ"
        mock_action.value = None  # Will be calculated

        new_action = Mock(spec=ControlActionSchema)
        mock_action.model_copy.return_value = new_action
        mock_condition.action = mock_action

        # Single temperature: 29°C
        snapshot = {"AIn01": 29.0}

        # Act
        result_action = control_evaluator._apply_policy_to_action(mock_condition, mock_action, snapshot)

        # Assert: base_freq + (temp - base_temp) * gain = 40 + (29 - 25) * 1.2 = 44.8
        assert result_action is new_action
        assert new_action.value == 44.8
        assert new_action.type == ControlActionType.SET_FREQUENCY

    def test_when_absolute_linear_at_base_temp_then_uses_base_frequency(self, control_evaluator):
        """Test that absolute_linear policy uses base frequency when temperature equals base_temp"""
        # Arrange
        mock_condition = Mock(spec=ConditionSchema)
        mock_policy = Mock()
        mock_policy.configure_mock(
            **{
                "type": "absolute_linear",
                "condition_type": "threshold",
                "sources": ["AIn01"],
                "base_freq": 40.0,
                "base_temp": 25.0,
                "gain_hz_per_unit": 1.2,
            }
        )
        mock_condition.policy = mock_policy

        mock_action = Mock(spec=ControlActionSchema)
        new_action = Mock(spec=ControlActionSchema)
        mock_action.model_copy.return_value = new_action
        mock_condition.action = mock_action

        # Temperature equals base_temp: 25°C
        snapshot = {"AIn01": 25.0}

        # Act
        result_action = control_evaluator._apply_policy_to_action(mock_condition, mock_action, snapshot)

        # Assert: base_freq + (25 - 25) * 1.2 = 40.0
        assert result_action is new_action
        assert new_action.value == 40.0
        assert new_action.type == ControlActionType.SET_FREQUENCY

    def test_when_incremental_linear_then_calculates_adjustment(self, control_evaluator):
        """Test that incremental_linear policy calculates frequency adjustment (no max_step limitation)"""
        # Arrange
        mock_condition = Mock(spec=ConditionSchema)
        mock_policy = Mock()
        mock_policy.configure_mock(
            **{
                "type": "incremental_linear",
                "condition_type": "difference",
                "sources": ["AIn01", "AIn02"],
                "gain_hz_per_unit": 1.5,
            }
        )
        mock_condition.policy = mock_policy

        mock_action = Mock(spec=ControlActionSchema)
        new_action = Mock(spec=ControlActionSchema)
        mock_action.model_copy.return_value = new_action
        mock_condition.action = mock_action

        # Temperature difference: 27 - 20 = 7°C
        snapshot = {"AIn01": 27.0, "AIn02": 20.0}

        # Act
        result_action = control_evaluator._apply_policy_to_action(mock_condition, mock_action, snapshot)

        # Assert
        assert result_action is new_action
        assert new_action.type == ControlActionType.ADJUST_FREQUENCY
        assert new_action.value == 1.5

    def test_when_incremental_linear_negative_diff_then_calculates_negative_adjustment(self, control_evaluator):
        """Test that incremental_linear policy calculates negative adjustment for negative temperature difference"""
        # Arrange
        mock_condition = Mock(spec=ConditionSchema)
        mock_policy = Mock()
        mock_policy.configure_mock(
            **{
                "type": "incremental_linear",
                "condition_type": "difference",
                "sources": ["AIn01", "AIn02"],
                "gain_hz_per_unit": -1.5,
            }
        )
        mock_condition.policy = mock_policy

        mock_action = Mock(spec=ControlActionSchema)
        new_action = Mock(spec=ControlActionSchema)
        mock_action.model_copy.return_value = new_action
        mock_condition.action = mock_action

        # Negative temperature difference: 18 - 25 = -7°C
        snapshot = {"AIn01": 18.0, "AIn02": 25.0}

        # Act
        result_action = control_evaluator._apply_policy_to_action(mock_condition, mock_action, snapshot)

        # Assert
        assert result_action is new_action
        assert new_action.type == ControlActionType.ADJUST_FREQUENCY
        assert new_action.value == -1.5

    def test_when_absolute_linear_then_calculates_absolute_frequency(self, control_evaluator):
        """Test that absolute_linear policy calculates absolute frequency based on single temperature"""
        # Arrange
        mock_condition = Mock(spec=ConditionSchema)
        mock_condition.code = "ABS_TEMP01"

        # absolute_linear policy with correct configuration
        mock_policy = Mock()
        mock_policy.configure_mock(
            **{
                "type": "absolute_linear",
                "condition_type": "threshold",
                "sources": ["AIn01"],
                "base_freq": 40.0,
                "base_temp": 25.0,
                "gain_hz_per_unit": 1.2,
            }
        )
        mock_condition.policy = mock_policy

        mock_action = Mock(spec=ControlActionSchema)
        mock_action.model = "TECO_VFD"
        mock_action.slave_id = "2"
        mock_action.type = "set_frequency"
        mock_action.target = "RW_HZ"
        mock_action.value = None  # Will be calculated

        new_action = Mock(spec=ControlActionSchema)
        mock_action.model_copy.return_value = new_action
        mock_condition.action = mock_action

        # Single temperature: 29°C
        snapshot = {"AIn01": 29.0}

        # Act
        result_action = control_evaluator._apply_policy_to_action(mock_condition, mock_action, snapshot)

        # Assert: base_freq + (temp - base_temp) * gain = 40 + (29 - 25) * 1.2 = 44.8
        assert result_action is new_action
        assert new_action.value == 44.8
        assert new_action.type == ControlActionType.SET_FREQUENCY

    def test_when_condition_type_is_difference_then_calculates_difference_value(self, control_evaluator):
        """Test that _get_condition_value correctly calculates difference between two sources"""
        # Arrange
        mock_policy = Mock()
        mock_policy.configure_mock(**{"condition_type": "difference", "sources": ["AIn01", "AIn02"]})

        snapshot = {"AIn01": 25.5, "AIn02": 20.2}

        # Act
        result = control_evaluator._get_condition_value(mock_policy, snapshot)

        # Assert
        assert result is not None
        assert abs(result - (25.5 - 20.2)) < 0.001  # 5.3

    def test_when_source_data_is_missing_then_returns_none(self, control_evaluator):
        """Test that _get_condition_value returns None when source data is missing"""
        # Arrange
        mock_policy = Mock()
        mock_policy.configure_mock(**{"condition_type": "difference", "sources": ["AIn01", "AIn02"]})

        snapshot = {"AIn01": 25.0}  # Missing AIn02

        # Act
        result = control_evaluator._get_condition_value(mock_policy, snapshot)

        # Assert
        assert result is None

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
    """
    Integration tests for complete evaluation flow
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
        """Create ControlEvaluator with mocked dependencies"""
        evaluator = ControlEvaluator(mock_control_config, constraint_config_schema)
        # Mock the composite_evaluator
        evaluator.composite_evaluator = Mock()
        return evaluator

    def test_when_condition_matches_and_has_absolute_linear_policy_then_returns_calculated_action(
        self, control_evaluator, caplog
    ):
        caplog.set_level(logging.DEBUG)

        # Arrange
        mock_condition = Mock(spec=ConditionSchema)
        mock_condition.code = "ABS_TEMP01"
        mock_condition.name = "Environment Temperature Linear Control"
        mock_condition.priority = 90
        mock_condition.blocking = False

        # Setup composite
        mock_composite = Mock()
        mock_composite.invalid = False
        mock_condition.composite = mock_composite

        # Mock composite evaluator
        control_evaluator.composite_evaluator.evaluate_composite_node.return_value = True
        control_evaluator.composite_evaluator.build_composite_reason_summary.return_value = "threshold(AIn01 gt 25.0)"

        mock_policy = Mock()
        mock_policy.configure_mock(
            **{
                "type": "absolute_linear",
                "condition_type": "threshold",
                "sources": ["AIn01"],
                "base_freq": 40.0,
                "base_temp": 25.0,
                "gain_hz_per_unit": 1.2,
            }
        )
        mock_condition.policy = mock_policy

        mock_action = Mock(spec=ControlActionSchema)
        mock_action.model = "TECO_VFD"
        mock_action.slave_id = "2"
        mock_action.type = ControlActionType.SET_FREQUENCY
        mock_action.target = "RW_HZ"
        mock_action.value = None
        mock_action.emergency_override = False

        # Create a new action for model_copy
        new_action = Mock(spec=ControlActionSchema)
        new_action.model = "TECO_VFD"
        new_action.slave_id = "2"
        new_action.type = ControlActionType.SET_FREQUENCY
        new_action.target = "RW_HZ"
        new_action.value = None  # Will be set by the implementation
        new_action.reason = None
        new_action.emergency_override = False

        mock_action.model_copy.return_value = new_action

        mock_condition.actions = [mock_action]

        # Mock control_config.get_control_list
        control_evaluator.control_config.get_control_list.return_value = [mock_condition]

        snapshot = {"AIn01": 29.0}
        # Act
        result = control_evaluator.evaluate("TECO_VFD", "2", snapshot)

        # Assert
        assert len(result) == 1, f"Expected 1 result but got {len(result)}. Result: {result}"

        action = result[0]
        # Expected value：base_freq + (temp - base_temp) * gain = 40.0 + (29-25)*1.2 = 44.8
        expected_freq = 40.0 + (29.0 - 25.0) * 1.2  # = 44.8
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
