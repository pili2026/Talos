import logging

import pytest

from core.device.generic.constraints_policy import ConstraintPolicy
from core.schema.constraint_schema import ConstraintConfig


class TestConstraintPolicy:
    @pytest.fixture
    def mock_logger(self):
        return logging.getLogger("test")

    def test_when_value_within_range_then_allowed(self, mock_logger):
        """Test that a value within the constraint range is allowed"""
        # Arrange
        constraints = {"RW_HZ": ConstraintConfig(min=30.0, max=55.0)}
        policy = ConstraintPolicy(constraints, mock_logger)

        # Act
        result = policy.allow("RW_HZ", 40.0)

        # Assert
        assert result is True

    def test_when_value_below_minimum_then_rejected(self, mock_logger):
        """Test that a value below the minimum is rejected"""
        # Arrange
        constraints = {"RW_HZ": ConstraintConfig(min=30.0, max=55.0)}
        policy = ConstraintPolicy(constraints, mock_logger)

        # Act
        result = policy.allow("RW_HZ", 25.0)

        # Assert
        assert result is False

    def test_when_value_above_maximum_then_rejected(self, mock_logger):
        """Test that a value above the maximum is rejected"""
        # Arrange
        constraints = {"RW_HZ": ConstraintConfig(min=30.0, max=55.0)}
        policy = ConstraintPolicy(constraints, mock_logger)

        # Act
        result = policy.allow("RW_HZ", 60.0)

        # Assert
        assert result is False

    def test_when_no_constraint_exists_then_all_values_allowed(self, mock_logger):
        """Test that all values are allowed when no constraint exists"""
        # Arrange
        policy = ConstraintPolicy({}, mock_logger)

        # Act
        result = policy.allow("UNKNOWN_TARGET", 999.0)

        # Assert
        assert result is True

    def test_when_min_and_max_are_none_then_all_values_allowed(self, mock_logger):
        """Test that None min/max are treated as infinite range"""
        # Arrange
        constraints = {"RW_HZ": ConstraintConfig(min=None, max=None)}
        policy = ConstraintPolicy(constraints, mock_logger)

        # Act & Assert
        assert policy.allow("RW_HZ", -999.0) is True
        assert policy.allow("RW_HZ", 999.0) is True
