import pytest

from schema.constraint_schema import ConstraintConfig, ConstraintConfigSchema
from util.config_manager import ConfigManager


class TestConfigManagerStartupFrequency:
    @pytest.fixture
    def sample_config(self):
        return ConstraintConfigSchema(
            **{
                "global_defaults": {"initialization": {"startup_frequency": 50.0}},
                "LITEON_EVO6800": {
                    "initialization": {"startup_frequency": 45.0},
                    "instances": {
                        "1": {"initialization": {"startup_frequency": 52.0}},
                        "2": {},  # No instance setting, should use model default
                    },
                },
                "TECO_VFD": {
                    # No model-level setting, should use global default
                },
            }
        )

    def test_when_instance_config_exists_then_returns_instance_value(self, sample_config):
        """Test that instance-level startup frequency takes highest priority"""
        # Arrange
        model = "LITEON_EVO6800"
        slave_id = 1

        # Act
        freq = ConfigManager.get_device_startup_frequency(sample_config, model, slave_id)

        # Assert
        assert freq == 52.0

    def test_when_no_instance_config_then_returns_model_default(self, sample_config):
        """Test that model-level default is used when no instance setting exists"""
        # Arrange
        model = "LITEON_EVO6800"
        slave_id = 2

        # Act
        freq = ConfigManager.get_device_startup_frequency(sample_config, model, slave_id)

        # Assert
        assert freq == 45.0

    def test_when_no_model_config_then_returns_global_default(self, sample_config):
        """Test that global default is used when no model-level config exists"""
        # Arrange
        model = "TECO_VFD"
        slave_id = 5

        # Act
        freq = ConfigManager.get_device_startup_frequency(sample_config, model, slave_id)

        # Assert
        assert freq == 50.0

    def test_when_no_global_defaults_exist_then_returns_none(self):
        """Test that None is returned when no global default exists"""
        # Arrange
        config = ConstraintConfigSchema(**{"LITEON_EVO6800": {"initialization": {"startup_frequency": 45.0}}})

        # Act
        freq = ConfigManager.get_device_startup_frequency(config, "UNKNOWN_MODEL", 1)

        # Assert
        assert freq is None

    def test_when_unknown_device_but_global_exists_then_returns_global_default(self, sample_config):
        """Test that global default is used when device is unknown"""
        # Arrange
        model = "UNKNOWN_MODEL"
        slave_id = 1

        # Act
        freq = ConfigManager.get_device_startup_frequency(sample_config, model, slave_id)

        # Assert
        assert freq == 50.0


class TestConfigManagerConstraints:
    @pytest.fixture
    def constraint_config(self):
        return ConstraintConfigSchema(
            **{
                "LITEON_EVO6800": {
                    "default_constraints": {"RW_HZ": {"min": 30, "max": 55}, "RW_CURRENT": {"min": 0, "max": 100}},
                    "instances": {
                        "1": {"constraints": {"RW_HZ": {"min": 55, "max": 57}}},
                        "2": {"use_default_constraints": True},
                    },
                }
            }
        )

    def test_when_instance_constraint_override_then_instance_values_take_precedence(self, constraint_config):
        """Test that instance constraints override default constraints"""
        # Arrange
        model = "LITEON_EVO6800"
        slave_id = 1

        # Act
        constraints = ConfigManager.get_instance_constraints_from_schema(constraint_config, model, slave_id)

        # Assert
        assert isinstance(constraints["RW_HZ"], ConstraintConfig)
        assert constraints["RW_HZ"].min == 55
        assert constraints["RW_HZ"].max == 57

    def test_when_use_default_constraints_flag_then_defaults_are_applied(self, constraint_config):
        """Test that default constraints are applied when use_default_constraints flag is set"""
        # Arrange
        model = "LITEON_EVO6800"
        slave_id = 2

        # Act
        constraints = ConfigManager.get_instance_constraints_from_schema(constraint_config, model, slave_id)

        # Assert
        assert constraints["RW_HZ"].min == 30
        assert constraints["RW_HZ"].max == 55
        assert constraints["RW_CURRENT"].min == 0

    def test_when_unknown_device_then_returns_empty_dict(self, constraint_config):
        """Test that unknown device returns an empty dictionary"""
        # Arrange
        model = "UNKNOWN"
        slave_id = 1

        # Act
        constraints = ConfigManager.get_instance_constraints_from_schema(constraint_config, model, slave_id)

        # Assert
        assert constraints == {}
