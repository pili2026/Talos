"""
Integration tests for ConfigManager with YAMLManager support
"""

import pytest
import yaml

from core.schema.config_metadata import ConfigSource
from core.schema.constraint_schema import (
    ConstraintConfig,
    ConstraintConfigSchema,
    DeviceConfig,
    InitializationConfig,
    InstanceConfig,
)
from core.util.config_manager import ConfigManager
from core.util.yaml_manager import YAMLManager


@pytest.fixture
def temp_config_dir(tmp_path):
    """Create a temporary config directory"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def yaml_manager(temp_config_dir):
    """Create a YAMLManager instance"""
    return YAMLManager(temp_config_dir)


@pytest.fixture
def sample_constraint_config():
    """Create a sample constraint config"""
    return ConstraintConfigSchema(
        global_defaults=DeviceConfig(initialization=InitializationConfig(startup_frequency=50.0)),
        devices={
            "TECO_VFD": DeviceConfig(
                initialization=InitializationConfig(startup_frequency=50.0, auto_turn_on=True),
                default_constraints={"RW_HZ": ConstraintConfig(min=35, max=60)},
                instances={
                    "3": InstanceConfig(initialization=InitializationConfig(startup_frequency=45.0)),
                },
            ),
            "ADAM-4117": DeviceConfig(
                default_constraints={},
                instances={"12": InstanceConfig(), "14": InstanceConfig(pins={"AIn01": {"formula": [0, 5, -1]}})},
            ),
        },
    )


class TestConfigManagerLegacyMode:
    """Test ConfigManager in legacy mode (without YAMLManager)"""

    def test_given_no_yaml_manager_when_initializing_then_legacy_fields_are_unset(self):
        """Test initialization without YAMLManager"""
        manager = ConfigManager()
        assert manager.yaml_manager is None
        assert manager._constraint_config is None

    def test_given_config_file_when_loading_with_legacy_method_then_schema_is_loaded(
        self, temp_config_dir, sample_constraint_config, yaml_manager
    ):
        """Test legacy load_constraint_config() method"""
        # First, create a config file using YAMLManager
        yaml_manager.update_config("device_instance", sample_constraint_config)

        config_path = temp_config_dir / "device_instance.yml"

        # Load using legacy method
        config = ConfigManager.load_constraint_config(str(config_path))

        assert "TECO_VFD" in config.devices
        assert "ADAM-4117" in config.devices

        # Legacy mode doesn't track metadata generation (uses default)
        assert config.metadata.generation >= 1


class TestConfigManagerManagedMode:
    """Test ConfigManager in managed mode (with YAMLManager)"""

    def test_given_yaml_manager_when_initializing_then_managed_fields_are_set(self, yaml_manager):
        """Test initialization with YAMLManager"""
        manager = ConfigManager(yaml_manager=yaml_manager)
        assert manager.yaml_manager is yaml_manager
        assert manager._constraint_config is None

    def test_given_constraint_config_when_saving_then_loading_preserves_metadata_and_data(
        self, yaml_manager, sample_constraint_config
    ):
        """Test load and save in managed mode"""
        manager = ConfigManager(yaml_manager=yaml_manager)

        # Initial save
        manager.save_constraint_config_managed(
            sample_constraint_config, source=ConfigSource.EDGE, modified_by="test_user"
        )

        # Load back
        loaded = manager.load_constraint_config_managed()

        # Check metadata
        assert loaded.metadata.generation == 1
        assert loaded.metadata.config_source == ConfigSource.EDGE
        assert loaded.metadata.last_modified_by == "test_user"

        # Check data
        assert "TECO_VFD" in loaded.devices
        assert "ADAM-4117" in loaded.devices

    def test_given_multiple_saves_when_saving_again_then_generation_increments(
        self, yaml_manager, sample_constraint_config
    ):
        """Test that generation increments on each save"""
        manager = ConfigManager(yaml_manager=yaml_manager)

        # First save
        manager.save_constraint_config_managed(sample_constraint_config, modified_by="user1")
        config1 = manager.get_current_config()
        assert config1.metadata.generation == 1

        # Modify and save again
        config1.devices["NEW_DEVICE"] = DeviceConfig(instances={})
        manager.save_constraint_config_managed(config1, modified_by="user2")

        # Reload and check
        config2 = manager.load_constraint_config_managed()
        assert config2.metadata.generation == 2
        assert config2.metadata.last_modified_by == "user2"
        assert "NEW_DEVICE" in config2.devices

    def test_given_no_yaml_manager_when_calling_managed_methods_then_value_error_is_raised(self):
        """Test that managed methods raise error without YAMLManager"""
        manager = ConfigManager()  # No YAMLManager

        with pytest.raises(ValueError, match="YAMLManager not initialized"):
            manager.load_constraint_config_managed()

        with pytest.raises(ValueError, match="YAMLManager not initialized"):
            manager.save_constraint_config_managed()

    def test_given_no_current_config_when_saving_then_value_error_is_raised(self, yaml_manager):
        """Test that save without config raises error"""
        manager = ConfigManager(yaml_manager=yaml_manager)

        with pytest.raises(ValueError, match="No config to save"):
            manager.save_constraint_config_managed()

    def test_given_external_change_when_reloading_then_latest_config_is_loaded(
        self, yaml_manager, sample_constraint_config
    ):
        """Test reloading configuration"""
        manager = ConfigManager(yaml_manager=yaml_manager)

        # Initial save
        manager.save_constraint_config_managed(sample_constraint_config)

        # Load
        config1 = manager.load_constraint_config_managed()
        gen1 = config1.metadata.generation

        # Modify directly via yaml_manager (simulating external change)
        config1.devices["EXTERNAL_CHANGE"] = DeviceConfig(instances={})
        yaml_manager.update_config("device_instance", config1, config_source=ConfigSource.CLOUD)

        # Reload should get the new version
        config2 = manager.reload_constraint_config()
        assert config2.metadata.generation > gen1
        assert "EXTERNAL_CHANGE" in config2.devices
        assert config2.metadata.config_source == ConfigSource.CLOUD


class TestConfigManagerBusinessLogic:
    """Test business logic methods work with both modes"""

    def test_given_hierarchical_startup_frequency_when_querying_then_instance_model_global_are_applied_in_order(
        self, sample_constraint_config
    ):
        """Test startup frequency hierarchical lookup"""
        # Instance level (highest priority)
        freq = ConfigManager.get_device_startup_frequency(sample_constraint_config, "TECO_VFD", 3)
        assert freq == 45.0  # Instance override

        # Model level
        freq = ConfigManager.get_device_startup_frequency(sample_constraint_config, "TECO_VFD", 5)  # No instance config
        assert freq == 50.0  # Model level

        # Global level
        freq = ConfigManager.get_device_startup_frequency(sample_constraint_config, "UNKNOWN_DEVICE", 1)
        assert freq == 50.0  # Global default

    def test_given_instance_uses_default_constraints_when_querying_then_model_constraints_are_returned(
        self, sample_constraint_config
    ):
        """Test constraint retrieval"""
        # Add instance "1" that uses default constraints
        sample_constraint_config.devices["TECO_VFD"].instances["1"] = InstanceConfig(use_default_constraints=True)

        constraints = ConfigManager.get_instance_constraints_from_schema(sample_constraint_config, "TECO_VFD", 1)

        assert "RW_HZ" in constraints
        assert constraints["RW_HZ"].min == 35
        assert constraints["RW_HZ"].max == 60

    def test_given_instance_has_pin_overrides_when_querying_then_pin_overrides_are_returned(
        self, sample_constraint_config
    ):
        """Test pin override retrieval"""
        pins = ConfigManager.get_instance_pins_from_schema(sample_constraint_config, "ADAM-4117", 14)

        assert "AIn01" in pins
        assert pins["AIn01"]["formula"] == [0, 5, -1]

    def test_given_auto_turn_on_defined_at_model_level_when_querying_then_auto_turn_on_is_true(
        self, sample_constraint_config
    ):
        """Test auto_turn_on hierarchical lookup"""
        # Model level
        auto_on = ConfigManager.get_device_auto_turn_on(sample_constraint_config, "TECO_VFD", 1)
        assert auto_on is True


class TestConfigManagerMigrationScenarios:
    """Test migration scenarios from legacy to managed mode"""

    def test_given_legacy_loaded_config_when_saving_managed_then_generation_increments(
        self, temp_config_dir, sample_constraint_config, yaml_manager
    ):
        """Test loading with legacy method, saving with managed method"""
        # Create config file using YAMLManager
        yaml_manager.update_config("device_instance", sample_constraint_config)
        config_path = temp_config_dir / "device_instance.yml"

        # Load using legacy method
        config = ConfigManager.load_constraint_config(str(config_path))

        # Save using managed method
        manager = ConfigManager(yaml_manager=yaml_manager)
        manager.save_constraint_config_managed(config, source=ConfigSource.EDGE, modified_by="migration_user")

        # Reload and verify
        reloaded = manager.load_constraint_config_managed()
        assert reloaded.metadata.generation == 2  # Incremented
        assert reloaded.metadata.last_modified_by == "migration_user"

    def test_given_existing_legacy_yaml_when_migrating_gradually_then_managed_config_is_saved(
        self, temp_config_dir, sample_constraint_config
    ):
        """Test gradual migration pattern"""
        # Start with legacy
        config_path = temp_config_dir / "device_instance.yml"

        data = sample_constraint_config.model_dump(by_alias=True, mode="json")
        with open(config_path, "w") as f:
            yaml.dump(data, f)

        # Create YAMLManager for new operations
        yaml_manager = YAMLManager(temp_config_dir)

        # Load with legacy, save with managed
        config_legacy = ConfigManager.load_constraint_config(str(config_path))

        manager = ConfigManager(yaml_manager=yaml_manager)
        manager.save_constraint_config_managed(config_legacy, source=ConfigSource.EDGE, modified_by="gradual_migration")

        # Now fully managed
        config_managed = manager.load_constraint_config_managed()
        assert config_managed.metadata.generation >= 1
        assert config_managed.metadata.last_modified_by == "gradual_migration"


class TestConfigManagerWithBackup:
    """Test ConfigManager leverages YAMLManager's backup features"""

    def test_given_second_save_when_saving_again_then_backup_is_created(self, yaml_manager, sample_constraint_config):
        """Test that saves create backups"""
        manager = ConfigManager(yaml_manager=yaml_manager)

        # First save
        manager.save_constraint_config_managed(sample_constraint_config)
        backups = yaml_manager.list_backups("device_instance")
        assert len(backups) == 0  # No backup on first save

        # Second save
        sample_constraint_config.devices["NEW"] = DeviceConfig(instances={})
        manager.save_constraint_config_managed(sample_constraint_config)

        backups = yaml_manager.list_backups("device_instance")
        assert len(backups) == 1  # Backup created

    def test_given_backup_restored_when_reloading_then_changes_are_reverted(
        self, yaml_manager, sample_constraint_config
    ):
        """Test restoring from backup through YAMLManager"""
        manager = ConfigManager(yaml_manager=yaml_manager)

        # Save initial config
        manager.save_constraint_config_managed(sample_constraint_config)

        # Modify and save
        sample_constraint_config.devices["TEMP"] = DeviceConfig(instances={})
        manager.save_constraint_config_managed(sample_constraint_config)

        # Restore backup
        backups = yaml_manager.list_backups("device_instance")
        if backups:
            yaml_manager.restore_backup(backups[0], "device_instance")

        # Reload and verify
        restored = manager.reload_constraint_config()
        assert "TEMP" not in restored.devices  # Modification reverted


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
