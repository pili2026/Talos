import pytest
from pydantic import ValidationError

from core.schema.constraint_schema import ConstraintConfigSchema


class TestConstraintConfigSchema:
    def test_when_config_is_complete_then_parses_successfully(self):
        """Test that a fully valid config parses correctly"""
        # Arrange
        config_data = {
            "global_defaults": {"initialization": {"startup_frequency": 50.0}},
            "LITEON_EVO6800": {
                "default_constraints": {"RW_HZ": {"min": 30, "max": 55}},
                "instances": {
                    "1": {
                        "initialization": {"startup_frequency": 52.0},
                        "constraints": {"RW_HZ": {"min": 55, "max": 57}},
                    }
                },
            },
        }

        # Act
        schema = ConstraintConfigSchema(**config_data)

        # Assert
        assert schema.global_defaults.initialization.startup_frequency == 50.0
        assert schema.devices["LITEON_EVO6800"].default_constraints["RW_HZ"].min == 30

    def test_when_optional_fields_missing_then_defaults_are_applied(self):
        """Test that missing optional fields fall back to defaults"""
        # Arrange
        config_data = {"TECO_VFD": {"default_constraints": {"RW_HZ": {"min": 55}}}}

        # Act
        schema = ConstraintConfigSchema(**config_data)

        # Assert
        assert schema.global_defaults is None
        # Expect default max=60 when not provided
        assert schema.devices["TECO_VFD"].default_constraints["RW_HZ"].max == 60

    def test_when_invalid_data_types_then_raises_validation_error(self):
        """Test that invalid data types raise a ValidationError"""
        # Arrange
        config_data = {"LITEON_EVO6800": {"initialization": {"startup_frequency": "invalid"}}}

        # Act & Assert
        with pytest.raises(ValidationError):
            ConstraintConfigSchema(**config_data)

    def test_when_config_is_empty_then_schema_has_no_devices(self):
        """Test that an empty config results in empty schema"""
        # Arrange & Act
        schema = ConstraintConfigSchema()

        # Assert
        assert schema.global_defaults is None
        assert schema.devices == {}
