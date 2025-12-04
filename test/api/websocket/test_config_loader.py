"""
Tests for config_loader utilities.

Tests YAML configuration loading and validation,
following Talos testing patterns.
"""

import pytest
import yaml
from pydantic import ValidationError

from api.websocket.monitoring_config import MonitoringConfig
from api.websocket.monitoring_config_loader import (
    EXAMPLE_CONFIG_YAML,
    create_default_config_file,
    load_monitoring_config_from_dict,
    load_monitoring_config_from_yaml,
    validate_config_file,
)


class TestLoadFromYAML:
    """Test loading MonitoringConfig from YAML files."""

    def test_when_valid_yaml_then_loads_successfully(self, tmp_path):
        """Test loading valid YAML configuration."""
        config_file = tmp_path / "monitoring.yml"
        config_data = {
            "max_consecutive_failures": 5,
            "default_single_device_interval": 2.0,
            "default_multi_device_interval": 3.0,
            "min_interval": 1.0,
            "max_interval": 120.0,
            "enable_control_commands": False,
        }

        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        config = load_monitoring_config_from_yaml(config_file)

        assert config.max_consecutive_failures == 5
        assert config.default_single_device_interval == 2.0
        assert config.default_multi_device_interval == 3.0
        assert config.min_interval == 1.0
        assert config.max_interval == 120.0
        assert config.enable_control_commands is False

    def test_when_partial_yaml_then_uses_defaults(self, tmp_path):
        """Test loading YAML with only some fields specified."""
        config_file = tmp_path / "monitoring.yml"
        config_data = {"max_consecutive_failures": 10}

        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        config = load_monitoring_config_from_yaml(config_file)

        assert config.max_consecutive_failures == 10
        # Defaults should be used for other fields
        assert config.default_single_device_interval == 1.0
        assert config.enable_control_commands is True

    def test_when_file_not_found_then_raises_error(self):
        """Test error when configuration file doesn't exist."""
        with pytest.raises(FileNotFoundError):
            load_monitoring_config_from_yaml("nonexistent.yml")

    def test_when_invalid_values_then_raises_validation_error(self, tmp_path):
        """Test validation error for invalid configuration values."""
        config_file = tmp_path / "monitoring.yml"
        config_data = {"max_consecutive_failures": 0}  # Invalid: must be >= 1

        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        with pytest.raises(ValidationError):
            load_monitoring_config_from_yaml(config_file)

    def test_when_empty_file_then_raises_error(self, tmp_path):
        """Test error when configuration file is empty."""
        config_file = tmp_path / "empty.yml"
        config_file.touch()

        with pytest.raises(ValueError, match="Empty configuration file"):
            load_monitoring_config_from_yaml(config_file)

    def test_when_malformed_yaml_then_raises_yaml_error(self, tmp_path):
        """Test error when YAML is malformed."""
        config_file = tmp_path / "malformed.yml"

        with open(config_file, "w", encoding="utf-8") as f:
            f.write("invalid: yaml: content: [")

        with pytest.raises(yaml.YAMLError):
            load_monitoring_config_from_yaml(config_file)


class TestLoadFromDict:
    """Test loading MonitoringConfig from dictionary."""

    def test_when_valid_dict_then_loads_successfully(self):
        """Test loading from valid dictionary."""
        config_dict = {
            "max_consecutive_failures": 7,
            "default_single_device_interval": 1.5,
        }

        config = load_monitoring_config_from_dict(config_dict)

        assert config.max_consecutive_failures == 7
        assert config.default_single_device_interval == 1.5

    def test_when_empty_dict_then_uses_all_defaults(self):
        """Test loading from empty dict uses all defaults."""
        config = load_monitoring_config_from_dict({})

        assert config.max_consecutive_failures == 3
        assert config.default_single_device_interval == 1.0

    def test_when_invalid_dict_then_raises_validation_error(self):
        """Test validation error for invalid dictionary."""
        with pytest.raises(ValidationError):
            load_monitoring_config_from_dict({"max_consecutive_failures": -1})


class TestCreateDefaultConfigFile:
    """Test creating default configuration files."""

    def test_when_create_default_then_file_exists(self, tmp_path):
        """Test creating default configuration file."""
        config_file = tmp_path / "default.yml"

        create_default_config_file(config_file)

        assert config_file.exists()

    def test_when_create_default_then_file_is_valid(self, tmp_path):
        """Test created default file is valid and loadable."""
        config_file = tmp_path / "default.yml"

        create_default_config_file(config_file)

        # Should be able to load it back
        config = load_monitoring_config_from_yaml(config_file)
        assert isinstance(config, MonitoringConfig)

    def test_when_create_default_then_contains_all_fields(self, tmp_path):
        """Test created file contains all configuration fields."""
        config_file = tmp_path / "default.yml"

        create_default_config_file(config_file)

        with open(config_file, "r") as f:
            config_data = yaml.safe_load(f)

        expected_fields = {
            "max_consecutive_failures",
            "default_single_device_interval",
            "default_multi_device_interval",
            "min_interval",
            "max_interval",
            "enable_control_commands",
        }

        assert set(config_data.keys()) == expected_fields

    def test_when_parent_dir_missing_then_creates_dirs(self, tmp_path):
        """Test that parent directories are created if they don't exist."""
        config_file = tmp_path / "nested" / "dirs" / "config.yml"

        create_default_config_file(config_file)

        assert config_file.exists()
        assert config_file.parent.exists()


class TestValidateConfigFile:
    """Test configuration file validation."""

    def test_when_valid_file_then_returns_true(self, tmp_path):
        """Test validation succeeds for valid file."""
        config_file = tmp_path / "valid.yml"
        create_default_config_file(config_file)

        is_valid, error = validate_config_file(config_file)

        assert is_valid is True
        assert error == ""

    def test_when_invalid_file_then_returns_false_with_message(self, tmp_path):
        """Test validation fails with error message for invalid file."""
        config_file = tmp_path / "invalid.yml"
        config_data = {"max_consecutive_failures": 0}  # Invalid

        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        is_valid, error = validate_config_file(config_file)

        assert is_valid is False
        assert "Validation error" in error

    def test_when_file_not_found_then_returns_false_with_message(self):
        """Test validation fails when file doesn't exist."""
        is_valid, error = validate_config_file("nonexistent.yml")

        assert is_valid is False
        assert "File not found" in error

    def test_when_malformed_yaml_then_returns_false_with_message(self, tmp_path):
        """Test validation fails for malformed YAML."""
        config_file = tmp_path / "malformed.yml"

        with open(config_file, "w", encoding="utf-8") as f:
            f.write("invalid: yaml: [")

        is_valid, error = validate_config_file(config_file)

        assert is_valid is False
        assert "YAML parsing error" in error


class TestExampleConfigYAML:
    """Test the example configuration."""

    def test_when_example_config_then_is_valid(self, tmp_path):
        """Test that the example configuration is valid."""
        config_file = tmp_path / "example.yml"

        with open(config_file, "w", encoding="utf-8") as f:
            f.write(EXAMPLE_CONFIG_YAML)

        config = load_monitoring_config_from_yaml(config_file)

        assert isinstance(config, MonitoringConfig)
        assert config.max_consecutive_failures == 3
        assert config.enable_control_commands is True


class TestIntegrationScenarios:
    """Test realistic usage scenarios."""

    def test_when_production_config_then_loads_correctly(self, tmp_path):
        """Test loading production-style configuration."""
        config_file = tmp_path / "production.yml"
        config_data = {
            "max_consecutive_failures": 5,
            "default_single_device_interval": 2.0,
            "default_multi_device_interval": 5.0,
            "min_interval": 1.0,
            "max_interval": 300.0,
            "enable_control_commands": True,
        }

        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        config = load_monitoring_config_from_yaml(config_file)

        assert config.max_consecutive_failures == 5
        assert config.validate_interval(2.0) is True
        assert config.validate_interval(0.5) is False  # Below min

    def test_when_development_config_then_loads_correctly(self, tmp_path):
        """Test loading development-style configuration."""
        config_file = tmp_path / "development.yml"
        config_data = {
            "max_consecutive_failures": 2,
            "default_single_device_interval": 0.5,
            "min_interval": 0.1,
        }

        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        config = load_monitoring_config_from_yaml(config_file)

        assert config.max_consecutive_failures == 2
        assert config.default_single_device_interval == 0.5
        assert config.min_interval == 0.1
