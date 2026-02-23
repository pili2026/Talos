"""
Tests for YAMLManager
"""

import time
from pathlib import Path

import pytest
import yaml

from core.schema.config_metadata import ConfigSource
from core.schema.constraint_schema import ConstraintConfigSchema, DeviceConfig, InitializationConfig
from core.schema.modbus_device_schema import ModbusBusConfig, ModbusDeviceConfig, ModbusDeviceFileConfig
from core.util.yaml_manager import YAMLManager


@pytest.fixture
def temp_config_dir(tmp_path):
    """Create a temporary config directory"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def yaml_manager(temp_config_dir):
    """Create a YAMLManager instance with temp directory"""
    return YAMLManager(temp_config_dir, backup_count=5)


@pytest.fixture
def sample_modbus_config():
    """Create a sample modbus device config"""
    return ModbusDeviceFileConfig(
        bus_dict={"rtu0": ModbusBusConfig(port="/dev/ttyUSB0", baudrate=9600, timeout=1.0)},
        device_list=[
            ModbusDeviceConfig(
                model="ADTEK_CPM10",
                type="power_meter",
                model_file="driver/adtek_cpm_10.yml",
                bus="rtu0",
                slave_id=1,
            )
        ],
    )


@pytest.fixture
def sample_device_instance_config():
    """Create a sample device instance config"""
    return ConstraintConfigSchema(
        global_defaults=DeviceConfig(initialization=InitializationConfig(startup_frequency=50.0)),
        devices={
            "TECO_VFD": DeviceConfig(
                initialization=InitializationConfig(startup_frequency=50.0),
                instances={},
            )
        },
    )


class TestYAMLManagerInit:
    """Test YAMLManager initialization"""

    def test_given_new_config_dir_when_initializing_then_directories_are_created(self, tmp_path):
        """Test that initialization creates necessary directories"""
        config_dir = tmp_path / "new_config"
        manager = YAMLManager(config_dir)

        assert config_dir.exists()
        assert (config_dir / "backups").exists()

    def test_given_string_path_when_initializing_then_path_is_supported(self, tmp_path):
        """Test initialization with string path"""
        config_dir = str(tmp_path / "config_str")
        manager = YAMLManager(config_dir)

        assert Path(config_dir).exists()

    def test_given_backup_count_when_initializing_then_backup_count_is_set(self, temp_config_dir):
        """Test that backup count is set correctly"""
        manager = YAMLManager(temp_config_dir, backup_count=20)
        assert manager.backup_count == 20


class TestYAMLManagerWrite:
    """Test config writing operations"""

    def test_given_new_config_when_updating_then_file_is_written_with_metadata(
        self, yaml_manager, sample_modbus_config
    ):
        """Test writing a new config file"""
        yaml_manager.update_config(
            "modbus_device",
            sample_modbus_config,
            config_source=ConfigSource.EDGE,
            modified_by="test_user",
        )

        # Check file exists
        config_path = yaml_manager.config_dir / "modbus_device.yml"
        assert config_path.exists()

        # Read back and verify
        loaded = yaml_manager.read_config("modbus_device")
        assert loaded.metadata.generation == 1
        assert loaded.metadata.config_source == ConfigSource.EDGE
        assert loaded.metadata.last_modified_by == "test_user"
        assert loaded.metadata.checksum is not None
        assert loaded.metadata.checksum.startswith("sha256:")

    def test_given_existing_config_when_updating_multiple_times_then_generation_increments(
        self, yaml_manager, sample_modbus_config
    ):
        """Test that generation increments on each update"""
        # First write
        yaml_manager.update_config("modbus_device", sample_modbus_config)
        config1 = yaml_manager.read_config("modbus_device")
        assert config1.metadata.generation == 1

        # Second write
        yaml_manager.update_config("modbus_device", sample_modbus_config)
        config2 = yaml_manager.read_config("modbus_device")
        assert config2.metadata.generation == 2

        # Third write
        yaml_manager.update_config("modbus_device", sample_modbus_config)
        config3 = yaml_manager.read_config("modbus_device")
        assert config3.metadata.generation == 3

    def test_given_config_content_changes_when_updating_then_checksum_is_recalculated(
        self, yaml_manager, sample_modbus_config
    ):
        """Test that checksum is recalculated on each update"""
        # Write initial config
        yaml_manager.update_config("modbus_device", sample_modbus_config)
        config1 = yaml_manager.read_config("modbus_device")
        checksum1 = config1.metadata.checksum

        # Modify config
        sample_modbus_config.device_list[0].slave_id = 2

        # Write modified config
        yaml_manager.update_config("modbus_device", sample_modbus_config)
        config2 = yaml_manager.read_config("modbus_device")
        checksum2 = config2.metadata.checksum

        # Checksums should be different
        assert checksum1 != checksum2

    def test_given_different_config_sources_when_updating_then_config_source_is_stored(
        self, yaml_manager, sample_modbus_config
    ):
        """Test writing with different sources"""
        # Write as EDGE
        yaml_manager.update_config("modbus_device", sample_modbus_config, config_source=ConfigSource.EDGE)
        config = yaml_manager.read_config("modbus_device")
        assert config.metadata.config_source == ConfigSource.EDGE

        # Write as CLOUD
        yaml_manager.update_config("modbus_device", sample_modbus_config, config_source=ConfigSource.CLOUD)
        config = yaml_manager.read_config("modbus_device")
        assert config.metadata.config_source == ConfigSource.CLOUD

    def test_given_unknown_config_type_when_updating_then_value_error_is_raised(
        self, yaml_manager, sample_modbus_config
    ):
        """Test that unknown config type raises ValueError"""
        with pytest.raises(ValueError, match="Unknown config type"):
            yaml_manager.update_config("unknown_type", sample_modbus_config)


class TestYAMLManagerRead:
    """Test config reading operations"""

    def test_given_missing_config_file_when_reading_then_file_not_found_is_raised(self, yaml_manager):
        """Test reading non-existent config raises FileNotFoundError"""
        with pytest.raises(FileNotFoundError):
            yaml_manager.read_config("modbus_device")

    def test_given_written_modbus_config_when_reading_then_all_data_is_preserved(
        self, yaml_manager, sample_modbus_config
    ):
        """Test that read preserves all data"""
        # Write config
        yaml_manager.update_config("modbus_device", sample_modbus_config)

        # Read back
        loaded = yaml_manager.read_config("modbus_device")

        # Verify data preserved
        assert len(loaded.bus_dict) == 1
        assert "rtu0" in loaded.bus_dict
        assert loaded.bus_dict["rtu0"].port == "/dev/ttyUSB0"

        assert len(loaded.device_list) == 1
        assert loaded.device_list[0].model == "ADTEK_CPM10"
        assert loaded.device_list[0].slave_id == 1

    def test_given_written_device_instance_config_when_reading_then_schema_is_loaded(
        self, yaml_manager, sample_device_instance_config
    ):
        """Test reading device instance config"""
        yaml_manager.update_config("device_instance_config", sample_device_instance_config)

        loaded = yaml_manager.read_config("device_instance_config")
        assert loaded.metadata.generation == 1
        assert "TECO_VFD" in loaded.devices


class TestYAMLManagerBackup:
    """Test backup functionality"""

    def test_given_existing_config_when_updating_then_backup_is_created(self, yaml_manager, sample_modbus_config):
        """Test that backup is created when updating existing config"""
        # First write (no backup expected)
        yaml_manager.update_config("modbus_device", sample_modbus_config)
        backups = yaml_manager.list_backups("modbus_device")
        assert len(backups) == 0

        # Second write (should create backup of gen 1)
        time.sleep(0.1)  # Ensure different timestamp
        yaml_manager.update_config("modbus_device", sample_modbus_config)
        backups = yaml_manager.list_backups("modbus_device")
        assert len(backups) == 1
        assert "gen1" in backups[0].name

    def test_given_create_backup_false_when_updating_then_no_backup_is_created(
        self, yaml_manager, sample_modbus_config
    ):
        """Test disabling backup creation"""
        # First write
        yaml_manager.update_config("modbus_device", sample_modbus_config)

        # Second write without backup
        yaml_manager.update_config("modbus_device", sample_modbus_config, create_backup=False)

        backups = yaml_manager.list_backups("modbus_device")
        assert len(backups) == 0

    def test_given_more_updates_than_backup_count_when_updating_then_old_backups_are_rotated(
        self, yaml_manager, sample_modbus_config
    ):
        """Test that old backups are removed"""
        # Create more backups than backup_count (5)
        for i in range(8):
            yaml_manager.update_config("modbus_device", sample_modbus_config)
            time.sleep(0.01)  # Small delay to ensure different timestamps

        backups = yaml_manager.list_backups("modbus_device")
        # Should keep only 5 most recent
        assert len(backups) <= 5

    def test_given_multiple_backups_when_listing_then_backups_are_sorted_newest_first(
        self, yaml_manager, sample_modbus_config
    ):
        """Test that backups are listed newest first"""
        # Create multiple backups
        for i in range(3):
            yaml_manager.update_config("modbus_device", sample_modbus_config)
            time.sleep(0.1)

        backups = yaml_manager.list_backups("modbus_device")

        # Check they are sorted newest first
        assert len(backups) == 2  # 3 writes = 2 backups
        if len(backups) >= 2:
            assert backups[0].stat().st_mtime >= backups[1].stat().st_mtime

    def test_given_backup_exists_when_restoring_then_config_is_restored(self, yaml_manager, sample_modbus_config):
        """Test restoring from backup"""
        # Create initial config
        yaml_manager.update_config("modbus_device", sample_modbus_config)
        config1 = yaml_manager.read_config("modbus_device")

        # Modify and update
        sample_modbus_config.device_list[0].slave_id = 99
        yaml_manager.update_config("modbus_device", sample_modbus_config)

        # Restore from backup
        backups = yaml_manager.list_backups("modbus_device")
        assert len(backups) > 0
        yaml_manager.restore_backup(backups[0], "modbus_device")

        # Verify restored
        restored = yaml_manager.read_config("modbus_device")
        assert restored.device_list[0].slave_id == 1  # Original value


class TestYAMLManagerMetadata:
    """Test metadata-specific operations"""

    def test_given_config_exists_when_getting_metadata_then_only_metadata_is_returned(
        self, yaml_manager, sample_modbus_config
    ):
        """Test getting just metadata without parsing full config"""
        yaml_manager.update_config("modbus_device", sample_modbus_config)

        metadata = yaml_manager.get_metadata("modbus_device")

        assert metadata.generation == 1
        assert metadata.config_source == ConfigSource.EDGE
        assert metadata.checksum is not None

    def test_given_config_written_when_reading_then_metadata_timestamps_are_set(
        self, yaml_manager, sample_modbus_config
    ):
        """Test that timestamps are set correctly"""
        before_write = yaml_manager.read_config
        yaml_manager.update_config("modbus_device", sample_modbus_config)

        config = yaml_manager.read_config("modbus_device")

        # Check timestamps exist and are ISO 8601
        assert config.metadata.last_modified is not None
        assert config.metadata.applied_at is not None
        assert "T" in config.metadata.last_modified
        assert "T" in config.metadata.applied_at


class TestYAMLManagerAtomicWrite:
    """Test atomic write behavior"""

    def test_given_write_failure_when_updating_then_no_partial_files_are_left(
        self, yaml_manager, sample_modbus_config, monkeypatch
    ):
        """Test that failed writes don't leave partial files"""
        # Write initial config
        yaml_manager.update_config("modbus_device", sample_modbus_config)

        # Simulate write failure after temp file creation
        original_replace = Path.replace

        def failing_replace(self, target):
            raise IOError("Simulated write failure")

        monkeypatch.setattr(Path, "replace", failing_replace)

        # Attempt update (should fail)
        with pytest.raises(IOError):
            yaml_manager.update_config("modbus_device", sample_modbus_config)

        # Original file should still exist and be valid
        config = yaml_manager.read_config("modbus_device")
        assert config.metadata.generation == 1  # Unchanged


class TestYAMLManagerValidation:
    """Test config validation"""

    def test_given_valid_data_when_validating_then_validation_passes(self, yaml_manager):
        """Test validation of valid config"""
        valid_data = {
            "_metadata": {"generation": 1, "source": "edge"},
            "buses": {"rtu0": {"port": "/dev/ttyUSB0", "baudrate": 9600, "timeout": 1.0}},
            "devices": [],
        }

        is_valid, error = yaml_manager.validate_config("modbus_device", valid_data)

        assert is_valid is True
        assert error is None

    def test_given_invalid_data_when_validating_then_validation_fails_with_error(self, yaml_manager):
        """Test validation of invalid config"""
        invalid_data = {
            "buses": {},
            "devices": [
                {
                    "model": "TEST",
                    # Missing required fields
                }
            ],
        }

        is_valid, error = yaml_manager.validate_config("modbus_device", invalid_data)

        assert is_valid is False
        assert error is not None

    def test_given_unknown_config_type_when_validating_then_validation_fails_with_unknown_type_error(
        self, yaml_manager
    ):
        """Test validation with unknown config type"""
        is_valid, error = yaml_manager.validate_config("unknown", {})

        assert is_valid is False
        assert "Unknown config type" in error


class TestYAMLManagerYAMLFormat:
    """Test YAML output format"""

    def test_given_config_written_when_reading_yaml_then_yaml_uses_field_aliases(
        self, yaml_manager, sample_modbus_config
    ):
        """Test that YAML uses proper field aliases"""
        yaml_manager.update_config("modbus_device", sample_modbus_config)

        # Read raw YAML
        config_path = yaml_manager.config_dir / "modbus_device.yml"
        with open(config_path, "r") as f:
            yaml_content = f.read()

        # Check for aliases (not Python field names)
        assert "_metadata:" in yaml_content
        assert "buses:" in yaml_content
        assert "devices:" in yaml_content

        # Should NOT have Python field names
        assert "bus_dict:" not in yaml_content
        assert "device_list:" not in yaml_content

    def test_given_config_written_when_reading_yaml_then_yaml_is_human_readable_and_valid(
        self, yaml_manager, sample_modbus_config
    ):
        """Test that generated YAML is human-readable"""
        yaml_manager.update_config("modbus_device", sample_modbus_config)

        config_path = yaml_manager.config_dir / "modbus_device.yml"
        with open(config_path, "r") as f:
            yaml_content = f.read()

        # Check basic formatting
        assert yaml_content.count("\n") > 5  # Multi-line
        assert "  " in yaml_content  # Indented

        # Verify it's valid YAML
        parsed = yaml.safe_load(yaml_content)
        assert isinstance(parsed, dict)


class TestYAMLManagerRoundTrip:
    """Test complete write-read cycles"""

    def test_given_modbus_device_config_when_write_then_read_then_roundtrip_preserves_metadata_and_data(
        self, yaml_manager, sample_modbus_config
    ):
        """Test writing and reading modbus device config"""
        # Write
        yaml_manager.update_config(
            "modbus_device",
            sample_modbus_config,
            config_source=ConfigSource.CLOUD,
            modified_by="test@example.com",
        )

        # Read
        loaded = yaml_manager.read_config("modbus_device")

        # Verify metadata
        assert loaded.metadata.generation == 1
        assert loaded.metadata.config_source == ConfigSource.CLOUD
        assert loaded.metadata.last_modified_by == "test@example.com"

        # Verify data
        assert len(loaded.bus_dict) == 1
        assert len(loaded.device_list) == 1

    def test_given_device_instance_config_when_write_then_read_then_roundtrip_preserves_metadata_and_data(
        self, yaml_manager, sample_device_instance_config
    ):
        """Test writing and reading device instance config"""
        # Write
        yaml_manager.update_config(
            "device_instance_config",
            sample_device_instance_config,
            modified_by="system",
        )

        # Read
        loaded = yaml_manager.read_config("device_instance_config")

        # Verify metadata
        assert loaded.metadata.generation == 1
        assert loaded.metadata.last_modified_by == "system"

        # Verify data
        assert loaded.global_defaults is not None
        assert "TECO_VFD" in loaded.devices


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
