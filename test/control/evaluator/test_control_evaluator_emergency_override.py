"""
Emergency Override Unit Tests for ControlEvaluator
Tests the emergency override logic that bypasses constraints for safety
"""

import pytest
from unittest.mock import Mock
from evaluator.control_evaluator import ControlEvaluator
from schema.control_condition_schema import ControlActionSchema
from schema.constraint_schema import ConstraintConfigSchema


class TestEmergencyOverrideLogic:
    """Unit tests for emergency override constraint logic"""

    @pytest.fixture
    def mock_control_config(self):
        return Mock()

    def test_when_constraint_max_below_60_then_override_to_60(self):
        """Test emergency override when constraint max < 60"""
        # Arrange: constraint max = 50
        constraint_config = ConstraintConfigSchema(
            **{"TECO_VFD": {"instances": {"2": {"constraints": {"RW_HZ": {"min": 0, "max": 50}}}}}}
        )

        evaluator = ControlEvaluator(Mock(), constraint_config)

        action = ControlActionSchema(
            model="TECO_VFD", slave_id="2", type="set_frequency", target="RW_HZ", value=60, emergency_override=True
        )

        # Act
        result = evaluator._handle_emergency_override(action)

        # Assert
        assert result.value == 60
        assert "Override constraint 50" in result.reason

    def test_when_constraint_max_equals_60_then_use_60(self):
        """Test emergency uses constraint when already at 60"""
        # Arrange: constraint max = 60
        constraint_config = ConstraintConfigSchema(
            **{"TECO_VFD": {"instances": {"2": {"constraints": {"RW_HZ": {"min": 0, "max": 60}}}}}}
        )

        evaluator = ControlEvaluator(Mock(), constraint_config)

        action = ControlActionSchema(
            model="TECO_VFD", slave_id="2", type="set_frequency", target="RW_HZ", value=60, emergency_override=True
        )

        # Act
        result = evaluator._handle_emergency_override(action)

        # Assert
        assert result.value == 60
        assert "Use constraint max: 60" in result.reason

    def test_when_constraint_max_none_then_use_original_value(self):
        """Test emergency uses original value when constraint unknown"""
        # Arrange: no constraint defined
        constraint_config = ConstraintConfigSchema(**{})

        evaluator = ControlEvaluator(Mock(), constraint_config)

        action = ControlActionSchema(
            model="TECO_VFD", slave_id="2", type="set_frequency", target="RW_HZ", value=60, emergency_override=True
        )

        # Act
        result = evaluator._handle_emergency_override(action)

        # Assert
        assert result.value == 60
        assert "original value" in result.reason.lower()


class TestConstraintMaxRetrieval:
    """Unit tests for _get_constraint_max logic"""

    def test_when_instance_constraint_exists_then_use_instance_max(self):
        """Test instance constraint takes precedence"""
        # Arrange
        constraint_config = ConstraintConfigSchema(
            **{
                "TECO_VFD": {
                    "default_constraints": {"RW_HZ": {"min": 0, "max": 50}},
                    "instances": {"2": {"constraints": {"RW_HZ": {"min": 0, "max": 55}}}},
                }
            }
        )

        evaluator = ControlEvaluator(Mock(), constraint_config)

        # Act
        result = evaluator._get_constraint_max("TECO_VFD", "2")

        # Assert
        assert result == 55  # Instance max, not default

    def test_when_no_instance_constraint_and_use_defaults_then_use_default_max(self):
        """Test falls back to default constraint"""
        # Arrange
        constraint_config = ConstraintConfigSchema(
            **{
                "TECO_VFD": {
                    "default_constraints": {"RW_HZ": {"min": 0, "max": 50}},
                    "instances": {"2": {"use_default_constraints": True}},
                }
            }
        )

        evaluator = ControlEvaluator(Mock(), constraint_config)

        # Act
        result = evaluator._get_constraint_max("TECO_VFD", "2")

        # Assert
        assert result == 50  # Default max

    def test_when_use_defaults_false_then_return_none(self):
        """Test returns None when explicitly not using defaults"""
        # Arrange
        constraint_config = ConstraintConfigSchema(
            **{
                "TECO_VFD": {
                    "default_constraints": {"RW_HZ": {"min": 0, "max": 50}},
                    "instances": {"2": {"use_default_constraints": False}},
                }
            }
        )

        evaluator = ControlEvaluator(Mock(), constraint_config)

        # Act
        result = evaluator._get_constraint_max("TECO_VFD", "2")

        # Assert
        assert result is None

    def test_when_device_not_found_then_return_none(self):
        """Test returns None when device doesn't exist"""
        # Arrange
        constraint_config = ConstraintConfigSchema(**{})

        evaluator = ControlEvaluator(Mock(), constraint_config)

        # Act
        result = evaluator._get_constraint_max("NONEXISTENT_DEVICE", "1")

        # Assert
        assert result is None

    def test_when_instance_not_found_then_check_defaults(self):
        """Test checks default constraints when instance doesn't exist"""
        # Arrange
        constraint_config = ConstraintConfigSchema(
            **{"TECO_VFD": {"default_constraints": {"RW_HZ": {"min": 0, "max": 50}}, "instances": {}}}
        )

        evaluator = ControlEvaluator(Mock(), constraint_config)

        # Act
        result = evaluator._get_constraint_max("TECO_VFD", "999")

        # Assert
        assert result == 50  # Falls back to default
