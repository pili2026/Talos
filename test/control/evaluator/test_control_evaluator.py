import pytest
import logging
from unittest.mock import Mock
from model.control_model import ControlActionModel, ControlConditionModel
from schema.control_config_schema import ControlConfig
from evaluator.control_evaluator import ControlEvaluator


class TestControlEvaluatorPolicyProcessing:
    """
    Test policy processing logic in ControlEvaluator
    Tests three policy types: discrete_setpoint, absolute_linear, incremental_linear
    """

    @pytest.fixture
    def mock_control_config(self):
        """Create mock ControlConfig for testing"""
        config = Mock(spec=ControlConfig)
        return config

    @pytest.fixture
    def control_evaluator(self, mock_control_config):
        return ControlEvaluator(mock_control_config)

    def test_when_discrete_setpoint_policy_then_returns_original_fixed_value(self, control_evaluator):
        """Test that discrete_setpoint policy returns the original fixed value from YAML"""
        # Arrange
        mock_condition = Mock(spec=ControlConditionModel)
        mock_condition.code = "HIGH_TEMP"
        mock_condition.name = "High Temperature Shutdown"
        mock_condition.priority = 80

        # discrete_setpoint policy
        mock_policy = Mock()
        mock_policy.configure_mock(**{"type": "discrete_setpoint"})
        mock_condition.policy = mock_policy

        # action with fixed value
        mock_action = Mock(spec=ControlActionModel)
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

    def test_when_absolute_linear_above_deadband_then_calculates_absolute_frequency(self, control_evaluator):
        """Test that absolute_linear policy calculates absolute frequency when condition exceeds deadband"""
        # Arrange
        mock_condition = Mock(spec=ControlConditionModel)
        mock_condition.code = "LIN_ABS01"

        # absolute_linear policy with proper getattr support
        mock_policy = Mock()
        mock_policy.configure_mock(
            **{
                "type": "absolute_linear",
                "condition_type": "difference",
                "sources": ["AIn01", "AIn02"],
                "abs": True,
                "deadband": 4.0,
                "base_freq": 40.0,
                "gain_hz_per_unit": 1.5,
            }
        )
        mock_condition.policy = mock_policy

        mock_action = Mock(spec=ControlActionModel)
        mock_action.model = "TECO_VFD"
        mock_action.slave_id = "2"
        mock_action.type = "set_frequency"
        mock_action.target = "RW_HZ"
        mock_action.value = None  # Will be calculated

        new_action = Mock(spec=ControlActionModel)
        mock_action.model_copy.return_value = new_action
        mock_condition.action = mock_action

        # Temperature difference: 25 - 20 = 5°C (above deadband 4°C)
        snapshot = {"AIn01": 25.0, "AIn02": 20.0}

        # Act
        result_action = control_evaluator._apply_policy_to_action(mock_condition, mock_action, snapshot)

        # Assert: base_freq + (|5| - deadband) * gain = 40 + (5 - 4) * 1.5 = 41.5
        assert result_action is new_action
        assert new_action.value == 41.5

    def test_when_absolute_linear_within_deadband_then_uses_base_frequency(self, control_evaluator):
        """Test that absolute_linear policy uses base frequency when condition is within deadband"""
        # Arrange
        mock_condition = Mock(spec=ControlConditionModel)
        mock_policy = Mock()
        mock_policy.configure_mock(
            **{
                "type": "absolute_linear",
                "condition_type": "difference",
                "sources": ["AIn01", "AIn02"],
                "abs": True,
                "deadband": 4.0,
                "base_freq": 40.0,
                "gain_hz_per_unit": 1.5,
            }
        )
        mock_condition.policy = mock_policy

        mock_action = Mock(spec=ControlActionModel)
        new_action = Mock(spec=ControlActionModel)
        mock_action.model_copy.return_value = new_action
        mock_condition.action = mock_action

        # Small temperature difference: 22 - 20 = 2°C (within deadband 4°C)
        snapshot = {"AIn01": 22.0, "AIn02": 20.0}

        # Act
        result_action = control_evaluator._apply_policy_to_action(mock_condition, mock_action, snapshot)

        # Assert: Should use base_freq = 40.0
        assert result_action is new_action
        assert new_action.value == 40.0

    def test_when_incremental_linear_above_deadband_then_calculates_positive_adjustment(self, control_evaluator):
        """Test that incremental_linear policy calculates positive adjustment when condition exceeds positive deadband"""
        # Arrange
        mock_condition = Mock(spec=ControlConditionModel)
        mock_policy = Mock()
        mock_policy.configure_mock(
            **{
                "type": "incremental_linear",
                "condition_type": "difference",
                "sources": ["AIn01", "AIn02"],
                "abs": False,
                "deadband": 4.0,
                "gain_hz_per_unit": 1.0,
                "max_step_hz": 2.0,
            }
        )
        mock_condition.policy = mock_policy

        mock_action = Mock(spec=ControlActionModel)
        new_action = Mock(spec=ControlActionModel)
        mock_action.model_copy.return_value = new_action
        mock_condition.action = mock_action

        # Temperature difference: 27 - 20 = 7°C (above deadband 4°C)
        snapshot = {"AIn01": 27.0, "AIn02": 20.0}

        # Act
        result_action = control_evaluator._apply_policy_to_action(mock_condition, mock_action, snapshot)

        # Assert: excess = 7 - 4 = 3°C, adjustment = 3 * 1.0 = 3Hz, but limited to 2Hz
        assert result_action is new_action
        assert new_action.type == "adjust_frequency"
        assert new_action.value == 2.0  # Limited by max_step_hz

    def test_when_incremental_linear_below_deadband_then_calculates_negative_adjustment(self, control_evaluator):
        """Test that incremental_linear policy calculates negative adjustment when condition is below negative deadband"""
        # Arrange
        mock_condition = Mock(spec=ControlConditionModel)
        mock_policy = Mock()
        mock_policy.configure_mock(
            **{
                "type": "incremental_linear",
                "condition_type": "difference",
                "sources": ["AIn01", "AIn02"],
                "abs": False,
                "deadband": 4.0,
                "gain_hz_per_unit": 1.0,
                "max_step_hz": 2.0,
            }
        )
        mock_condition.policy = mock_policy

        mock_action = Mock(spec=ControlActionModel)
        new_action = Mock(spec=ControlActionModel)
        mock_action.model_copy.return_value = new_action
        mock_condition.action = mock_action

        # Temperature difference: 15 - 20 = -5°C (below -deadband)
        snapshot = {"AIn01": 15.0, "AIn02": 20.0}

        # Act
        result_action = control_evaluator._apply_policy_to_action(mock_condition, mock_action, snapshot)

        # Assert: excess = -5 - (-4) = -1°C, adjustment = -1 * 1.0 = -1Hz
        assert result_action is new_action
        assert new_action.type == "adjust_frequency"
        assert new_action.value == -1.0

    def test_when_incremental_linear_within_deadband_then_returns_none(self, control_evaluator):
        """Test that incremental_linear policy returns None when condition is within deadband"""
        # Arrange
        mock_condition = Mock(spec=ControlConditionModel)
        mock_policy = Mock()
        mock_policy.configure_mock(
            **{
                "type": "incremental_linear",
                "condition_type": "difference",
                "sources": ["AIn01", "AIn02"],
                "abs": False,
                "deadband": 4.0,
            }
        )
        mock_condition.policy = mock_policy

        mock_action = Mock(spec=ControlActionModel)
        mock_condition.action = mock_action

        # Temperature difference: 22 - 20 = 2°C (within deadband)
        snapshot = {"AIn01": 22.0, "AIn02": 20.0}

        # Act
        result_action = control_evaluator._apply_policy_to_action(mock_condition, mock_action, snapshot)

        # Assert: Should return None (no adjustment needed)
        assert result_action is None

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
        mock_condition = Mock(spec=ControlConditionModel)
        mock_condition.policy = None

        mock_action = Mock(spec=ControlActionModel)
        snapshot = {}

        # Act
        result_action = control_evaluator._apply_policy_to_action(mock_condition, mock_action, snapshot)

        # Assert
        assert result_action is mock_action  # Should return original action unchanged

    def test_when_policy_type_is_unknown_then_returns_original_action(self, control_evaluator, caplog):
        """Test that original action is returned when policy type is unknown"""
        # Arrange
        caplog.set_level(logging.WARNING)
        mock_condition = Mock(spec=ControlConditionModel)
        mock_policy = Mock()
        mock_policy.configure_mock(**{"type": "unknown_policy_type"})
        mock_condition.policy = mock_policy

        mock_action = Mock(spec=ControlActionModel)
        snapshot = {}

        # Act
        result_action = control_evaluator._apply_policy_to_action(mock_condition, mock_action, snapshot)

        # Assert
        assert result_action is mock_action
        assert "Unknown policy type" in caplog.text


class TestControlEvaluatorIntegration:
    """
    Integration tests for complete evaluation flow
    """

    @pytest.fixture
    def mock_control_config(self):
        """Create mock ControlConfig for testing"""
        config = Mock(spec=ControlConfig)
        return config

    @pytest.fixture
    def control_evaluator(self, mock_control_config):
        """Create ControlEvaluator with mocked dependencies"""
        evaluator = ControlEvaluator(mock_control_config)
        # Mock the composite_evaluator
        evaluator.composite_evaluator = Mock()
        return evaluator

    def test_when_condition_matches_and_has_absolute_linear_policy_then_returns_calculated_action(
        self, control_evaluator, caplog
    ):
        caplog.set_level(logging.DEBUG)

        # Arrange
        mock_condition = Mock(spec=ControlConditionModel)
        mock_condition.code = "LIN_ABS01"
        mock_condition.name = "ΔT Linear → Absolute Frequency"
        mock_condition.priority = 90

        # Setup composite
        mock_composite = Mock()
        mock_composite.invalid = False
        mock_condition.composite = mock_composite

        # Mock composite evaluator
        control_evaluator.composite_evaluator.evaluate_composite_node.return_value = True
        control_evaluator.composite_evaluator.build_composite_reason_summary.return_value = (
            "difference(AIn01,AIn02 gt 4.0)"
        )

        # Setup policy
        mock_policy = Mock()
        mock_policy.configure_mock(
            **{
                "type": "absolute_linear",
                "condition_type": "difference",
                "sources": ["AIn01", "AIn02"],
                "abs": True,
                "deadband": 4.0,
                "base_freq": 40.0,
                "gain_hz_per_unit": 1.5,
            }
        )
        mock_condition.policy = mock_policy

        mock_action = Mock(spec=ControlActionModel)
        mock_action.model = "TECO_VFD"
        mock_action.slave_id = "2"
        mock_action.type = "set_frequency"
        mock_action.target = "RW_HZ"
        mock_action.value = None

        # Create a new action for model_copy
        new_action = Mock(spec=ControlActionModel)
        new_action.model = "TECO_VFD"
        new_action.slave_id = "2"
        new_action.type = "set_frequency"
        new_action.target = "RW_HZ"
        new_action.value = None  # Will be set by the implementation
        new_action.reason = None
        mock_action.model_copy.return_value = new_action

        mock_condition.action = mock_action

        # Mock control_config.get_control_list
        control_evaluator.control_config.get_control_list.return_value = [mock_condition]

        snapshot = {"AIn01": 26.0, "AIn02": 20.0}  # Difference = 6°C

        # policy_result = control_evaluator._apply_policy_to_action(mock_condition, mock_action, snapshot)

        # Act
        result = control_evaluator.evaluate("TECO_VFD", "2", snapshot)

        # Assert
        assert len(result) == 1, f"Expected 1 result but got {len(result)}. Result: {result}. Check debug output above."
        result_action = result[0]
        assert result_action is new_action
        # Verify that the value was calculated and set correctly
        # base_freq + (|6| - deadband) * gain = 40 + (6 - 4) * 1.5 = 43.0
        assert result_action.value == 43.0
        assert "LIN_ABS01" in result_action.reason

    def test_when_no_conditions_match_then_returns_empty_list(self, control_evaluator):
        """Test that empty list is returned when no conditions match"""
        # Arrange
        mock_condition = Mock(spec=ControlConditionModel)
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
