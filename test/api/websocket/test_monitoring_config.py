"""
Tests for WebSocket MonitoringConfig.

Tests focus on configuration validation and constraints.
Uses Pydantic for validation, consistent with Talos patterns.
"""

import pytest
from pydantic import ValidationError

from api.websocket.monitoring_config import MonitoringConfig, WebSocketLimits


class TestMonitoringConfigValidation:
    """Test MonitoringConfig validation logic."""

    def test_when_default_config_then_all_fields_valid(self):
        """Test default configuration is valid."""
        config = MonitoringConfig()

        assert config.max_consecutive_failures == 3
        assert config.default_single_device_interval == 1.0
        assert config.default_multi_device_interval == 2.0
        assert config.min_interval == 0.5
        assert config.max_interval == 60.0
        assert config.enable_control_commands is True

    def test_when_custom_config_then_accepts_valid_values(self):
        """Test custom configuration with valid values."""
        config = MonitoringConfig(
            max_consecutive_failures=5,
            default_single_device_interval=2.0,
            default_multi_device_interval=3.0,
            min_interval=1.0,
            max_interval=120.0,
        )

        assert config.max_consecutive_failures == 5
        assert config.default_single_device_interval == 2.0
        assert config.default_multi_device_interval == 3.0

    def test_when_max_failures_zero_then_raises_error(self):
        """Test that max_consecutive_failures must be at least 1."""
        with pytest.raises(ValidationError) as exc_info:
            MonitoringConfig(max_consecutive_failures=0)
        assert "greater than or equal to 1" in str(exc_info.value)

    def test_when_negative_max_failures_then_raises_error(self):
        """Test that negative max_consecutive_failures is invalid."""
        with pytest.raises(ValidationError) as exc_info:
            MonitoringConfig(max_consecutive_failures=-1)
        assert "greater than or equal to 1" in str(exc_info.value)

    def test_when_min_interval_zero_then_raises_error(self):
        """Test that min_interval must be positive."""
        with pytest.raises(ValidationError) as exc_info:
            MonitoringConfig(min_interval=0)
        assert "greater than 0" in str(exc_info.value)

    def test_when_min_interval_negative_then_raises_error(self):
        """Test that negative min_interval is invalid."""
        with pytest.raises(ValidationError) as exc_info:
            MonitoringConfig(min_interval=-1.0)
        assert "greater than 0" in str(exc_info.value)

    def test_when_max_less_than_min_interval_then_raises_error(self):
        """Test that max_interval must be greater than min_interval."""
        with pytest.raises(ValidationError) as exc_info:
            MonitoringConfig(min_interval=10.0, max_interval=5.0)
        assert "must be greater than min_interval" in str(exc_info.value)

    def test_when_max_equals_min_interval_then_raises_error(self):
        """Test that max_interval cannot equal min_interval."""
        with pytest.raises(ValidationError) as exc_info:
            MonitoringConfig(min_interval=5.0, max_interval=5.0)
        assert "must be greater than min_interval" in str(exc_info.value)

    def test_when_default_single_interval_out_of_bounds_then_raises_error(self):
        """Test that default_single_device_interval must be within bounds."""
        with pytest.raises(ValidationError) as exc_info:
            MonitoringConfig(default_single_device_interval=100.0, max_interval=60.0)
        assert "must be between" in str(exc_info.value)

    def test_when_default_multi_interval_out_of_bounds_then_raises_error(self):
        """Test that default_multi_device_interval must be within bounds."""
        with pytest.raises(ValidationError) as exc_info:
            MonitoringConfig(default_multi_device_interval=0.1, min_interval=0.5)
        assert "must be between" in str(exc_info.value)

    def test_when_validate_interval_within_bounds_then_returns_true(self):
        """Test validate_interval returns True for valid intervals."""
        config = MonitoringConfig()

        assert config.validate_interval(0.5) is True
        assert config.validate_interval(1.0) is True
        assert config.validate_interval(30.0) is True
        assert config.validate_interval(60.0) is True

    def test_when_validate_interval_below_min_then_returns_false(self):
        """Test validate_interval returns False for intervals below minimum."""
        config = MonitoringConfig()

        assert config.validate_interval(0.1) is False
        assert config.validate_interval(0.4) is False

    def test_when_validate_interval_above_max_then_returns_false(self):
        """Test validate_interval returns False for intervals above maximum."""
        config = MonitoringConfig()

        assert config.validate_interval(61.0) is False
        assert config.validate_interval(120.0) is False


class TestWebSocketLimits:
    """Test WebSocketLimits configuration."""

    def test_when_default_limits_then_all_fields_valid(self):
        """Test default limits configuration."""
        limits = WebSocketLimits()

        assert limits.max_active_connections == 100
        assert limits.max_devices_per_connection == 20
        assert limits.max_parameters_per_device == 50
        assert limits.connection_timeout == 30.0
        assert limits.read_timeout == 5.0
        assert limits.write_timeout == 5.0
        assert limits.max_message_size == 1024 * 1024

    def test_when_custom_limits_then_accepts_values(self):
        """Test custom limits configuration."""
        limits = WebSocketLimits(
            max_active_connections=200,
            max_devices_per_connection=50,
            connection_timeout=60.0,
        )

        assert limits.max_active_connections == 200
        assert limits.max_devices_per_connection == 50
        assert limits.connection_timeout == 60.0


class TestConfigurationUsage:
    """Test practical configuration usage scenarios."""

    def test_when_production_config_then_conservative_values(self):
        """Test production-safe configuration."""
        config = MonitoringConfig(
            max_consecutive_failures=5,  # More tolerant in production
            default_single_device_interval=2.0,  # Reduce polling frequency
            default_multi_device_interval=5.0,  # Even less frequent for multiple devices
            min_interval=1.0,  # Higher minimum to prevent overload
        )

        assert config.max_consecutive_failures == 5
        assert config.default_single_device_interval == 2.0
        assert config.default_multi_device_interval == 5.0

    def test_when_development_config_then_responsive_values(self):
        """Test development-friendly configuration."""
        config = MonitoringConfig(
            max_consecutive_failures=2,  # Fail fast for debugging
            default_single_device_interval=0.5,  # Quick updates
            min_interval=0.1,  # Allow very fast polling for testing
        )

        assert config.max_consecutive_failures == 2
        assert config.default_single_device_interval == 0.5
        assert config.min_interval == 0.1

    def test_when_checking_interval_validity_then_use_validate_method(self):
        """Test using validate_interval in application logic."""
        config = MonitoringConfig()

        # Simulate user input validation
        user_intervals = [0.1, 0.5, 1.0, 30.0, 60.0, 100.0]
        valid_intervals = [i for i in user_intervals if config.validate_interval(i)]

        assert valid_intervals == [0.5, 1.0, 30.0, 60.0]
