import pytest

from core.schema.constraint_schema import (
    ConstraintConfig,
    ConstraintConfigSchema,
    DeviceConfig,
    InitializationConfig,
    InstanceConfig,
)
from core.util.config_manager import ConfigManager


class TestConfigManagerAutoTurnOn:
    """Test ConfigManager.get_device_auto_turn_on with proper inheritance"""

    def test_when_no_config_then_returns_none(self):
        """Should return None when no auto_turn_on configured at any level"""
        schema = ConstraintConfigSchema(devices={"TECO_VFD": DeviceConfig()})

        result = ConfigManager.get_device_auto_turn_on(schema, "TECO_VFD", 1)

        assert result is None

    def test_when_only_global_config_then_uses_global(self):
        """Should use global config when no model/instance override"""
        schema = ConstraintConfigSchema(
            global_defaults=DeviceConfig(initialization=InitializationConfig(auto_turn_on=True)),
            devices={"TECO_VFD": DeviceConfig()},
        )

        result = ConfigManager.get_device_auto_turn_on(schema, "TECO_VFD", 1)

        assert result is True

    def test_when_model_overrides_global_then_uses_model(self):
        """Should use model config to override global"""
        schema = ConstraintConfigSchema(
            global_defaults=DeviceConfig(initialization=InitializationConfig(auto_turn_on=False)),
            devices={"TECO_VFD": DeviceConfig(initialization=InitializationConfig(auto_turn_on=True))},
        )

        result = ConfigManager.get_device_auto_turn_on(schema, "TECO_VFD", 1)

        assert result is True  # Model overrides global

    def test_when_instance_not_set_then_inherits_model(self):
        """Should inherit from model when instance doesn't set value"""
        schema = ConstraintConfigSchema(
            devices={
                "TECO_VFD": DeviceConfig(
                    initialization=InitializationConfig(auto_turn_on=True),
                    instances={"1": InstanceConfig(initialization=InitializationConfig(startup_frequency=50.0))},
                )
            }
        )

        result = ConfigManager.get_device_auto_turn_on(schema, "TECO_VFD", 1)

        assert result is True

    def test_when_instance_sets_false_then_returns_false(self):
        """Should respect explicit False at instance level"""
        schema = ConstraintConfigSchema(
            devices={
                "TECO_VFD": DeviceConfig(
                    initialization=InitializationConfig(auto_turn_on=True),
                    instances={"1": InstanceConfig(initialization=InitializationConfig(auto_turn_on=False))},
                )
            }
        )

        result = ConfigManager.get_device_auto_turn_on(schema, "TECO_VFD", 1)

        assert result is False  # Instance explicitly disables

    def test_yaml_config_scenario(self):
        """Test the exact scenario from your YAML config"""
        schema = ConstraintConfigSchema(
            devices={
                "TECO_VFD": DeviceConfig(
                    initialization=InitializationConfig(startup_frequency=50.0, auto_turn_on=True),  # Model level
                    instances={
                        "3": InstanceConfig(
                            initialization=InitializationConfig(
                                startup_frequency=50.0
                                # auto_turn_on NOT set at instance level
                            ),
                            constraints={"RW_HZ": ConstraintConfig(min=40, max=50)},
                        )
                    },
                )
            }
        )

        # Test instance "3" which doesn't set auto_turn_on
        result = ConfigManager.get_device_auto_turn_on(schema, "TECO_VFD", 3)

        assert result is True  # ← 應該從 model level 繼承！

    def test_three_level_inheritance(self):
        """Test three-level inheritance: global -> model -> instance"""
        schema = ConstraintConfigSchema(
            global_defaults=DeviceConfig(
                initialization=InitializationConfig(startup_frequency=40.0, auto_turn_on=False)
            ),
            devices={
                "TECO_VFD": DeviceConfig(
                    initialization=InitializationConfig(auto_turn_on=True),  # Override global
                    instances={
                        "1": InstanceConfig(initialization=InitializationConfig(startup_frequency=45.0))
                        # Only override frequency, inherit auto_turn_on from model
                    },
                )
            },
        )

        result = ConfigManager.get_device_auto_turn_on(schema, "TECO_VFD", 1)

        assert result is True  # Inherits from model (which overrides global)


class TestConfigManagerStartupFrequency:
    """Test that startup_frequency inheritance still works correctly"""

    def test_instance_overrides_model(self):
        """Should use instance frequency when specified"""
        schema = ConstraintConfigSchema(
            devices={
                "TECO_VFD": DeviceConfig(
                    initialization=InitializationConfig(startup_frequency=50.0),
                    instances={"1": InstanceConfig(initialization=InitializationConfig(startup_frequency=45.0))},
                )
            }
        )

        result = ConfigManager.get_device_startup_frequency(schema, "TECO_VFD", 1)

        assert result == 45.0

    def test_inherits_from_model_when_not_set(self):
        """Should inherit model frequency when instance doesn't specify"""
        schema = ConstraintConfigSchema(
            devices={
                "TECO_VFD": DeviceConfig(
                    initialization=InitializationConfig(startup_frequency=50.0),
                    instances={"1": InstanceConfig(initialization=InitializationConfig(auto_turn_on=True))},
                )
            }
        )

        result = ConfigManager.get_device_startup_frequency(schema, "TECO_VFD", 1)

        assert result == 50.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
