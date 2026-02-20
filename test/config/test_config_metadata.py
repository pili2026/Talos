"""
Tests for Configuration Metadata and Schemas
"""

from datetime import datetime

import pytest
import yaml

from core.schema.config_metadata import ConfigMetadata, ConfigSource, calculate_config_checksum, increment_generation
from core.schema.constraint_schema import ConstraintConfigSchema, DeviceConfig, InitializationConfig
from core.schema.modbus_device_schema import ModbusBusConfig, ModbusDeviceConfig, ModbusDeviceFileConfig


class TestConfigMetadata:
    """Test ConfigMetadata schema"""

    def test_given_no_values_when_creating_metadata_then_defaults_are_applied(self):
        """Test metadata with default values"""
        metadata = ConfigMetadata()

        assert metadata.generation == 1
        assert metadata.config_source == ConfigSource.EDGE
        assert metadata.last_modified is not None
        assert metadata.last_modified_by is None
        assert metadata.checksum is None
        assert metadata.applied_at is None
        assert metadata.cloud_sync_id is None

    def test_given_custom_values_when_creating_metadata_then_values_are_preserved(self):
        """Test metadata with custom values"""
        metadata = ConfigMetadata(
            generation=5,
            config_source=ConfigSource.CLOUD,
            last_modified="2025-02-14T10:30:45Z",
            last_modified_by="jeremy@example.com",
            checksum="sha256:abc123",
            applied_at="2025-02-14T10:31:00Z",
            cloud_sync_id="cfg-001",
        )

        assert metadata.generation == 5
        assert metadata.config_source == ConfigSource.CLOUD
        assert metadata.last_modified == "2025-02-14T10:30:45Z"
        assert metadata.last_modified_by == "jeremy@example.com"
        assert metadata.checksum == "sha256:abc123"
        assert metadata.applied_at == "2025-02-14T10:31:00Z"
        assert metadata.cloud_sync_id == "cfg-001"

    def test_given_invalid_generation_when_creating_metadata_then_generation_falls_back_to_one(self):
        """Test generation number validation"""
        # Valid generation
        metadata = ConfigMetadata(generation=10)
        assert metadata.generation == 10

        # Invalid generation (< 1) should fallback to 1
        metadata = ConfigMetadata(generation=0)
        assert metadata.generation == 1

        metadata = ConfigMetadata(generation=-5)
        assert metadata.generation == 1

        # None should default to 1
        metadata = ConfigMetadata(generation=None)
        assert metadata.generation == 1

    def test_given_last_modified_when_creating_metadata_then_datetime_is_validated_or_replaced(self):
        """Test ISO 8601 datetime validation"""
        # Valid ISO 8601
        metadata = ConfigMetadata(last_modified="2025-02-14T10:30:45Z")
        assert metadata.last_modified == "2025-02-14T10:30:45Z"

        # Valid ISO 8601 with timezone
        metadata = ConfigMetadata(last_modified="2025-02-14T10:30:45+08:00")
        assert metadata.last_modified == "2025-02-14T10:30:45+08:00"

        # Invalid datetime should use current time
        metadata = ConfigMetadata(last_modified="invalid-datetime")
        assert metadata.last_modified is not None
        # Should be parseable as ISO 8601
        datetime.fromisoformat(metadata.last_modified.replace("Z", "+00:00"))

    def test_given_metadata_when_increment_generation_called_then_generation_is_increased(self):
        """Test generation increment helper"""
        metadata = ConfigMetadata(generation=5)
        next_gen = increment_generation(metadata)
        assert next_gen == 6

    def test_given_metadata_when_serialized_with_alias_then_fields_are_correct(self):
        """Test that metadata serializes with _metadata alias"""
        metadata = ConfigMetadata(generation=3, config_source=ConfigSource.CLOUD)

        # Serialize with alias
        data = metadata.model_dump(by_alias=True)
        # Keys should be normal (not aliased at this level)
        assert "generation" in data
        assert data["generation"] == 3
        assert data["config_source"] == "cloud"


class TestCalculateChecksum:
    """Test checksum calculation"""

    def test_given_simple_config_when_calculating_checksum_then_sha256_checksum_is_generated(self):
        """Test checksum calculation for simple config"""
        config_data = {"buses": {"rtu0": {"port": "/dev/ttyUSB0", "baudrate": 9600}}, "devices": []}

        checksum = calculate_config_checksum(config_data)
        assert checksum.startswith("sha256:")
        assert len(checksum) == 71  # "sha256:" + 64 hex chars

    def test_given_config_with_metadata_when_calculating_checksum_then_metadata_is_excluded(self):
        """Test that checksum excludes _metadata"""
        config_with_metadata = {
            "_metadata": {"generation": 5, "checksum": "old-checksum"},
            "buses": {"rtu0": {"port": "/dev/ttyUSB0"}},
        }

        config_without_metadata = {"buses": {"rtu0": {"port": "/dev/ttyUSB0"}}}

        checksum1 = calculate_config_checksum(config_with_metadata)
        checksum2 = calculate_config_checksum(config_without_metadata)

        # Should be identical since metadata is excluded
        assert checksum1 == checksum2

    def test_given_same_config_when_calculating_checksum_multiple_times_then_checksum_is_consistent(self):
        """Test that same config produces same checksum"""
        config = {"buses": {"rtu0": {"port": "/dev/ttyUSB0", "baudrate": 9600}}}

        checksum1 = calculate_config_checksum(config)
        checksum2 = calculate_config_checksum(config)

        assert checksum1 == checksum2

    def test_given_different_configs_when_calculating_checksum_then_checksum_changes(self):
        """Test that different configs produce different checksums"""
        config1 = {"buses": {"rtu0": {"port": "/dev/ttyUSB0", "baudrate": 9600}}}
        config2 = {"buses": {"rtu0": {"port": "/dev/ttyUSB0", "baudrate": 19200}}}

        checksum1 = calculate_config_checksum(config1)
        checksum2 = calculate_config_checksum(config2)

        assert checksum1 != checksum2


class TestModbusDeviceFileConfig:
    """Test ModbusDeviceFileConfig with metadata"""

    def test_given_yaml_with_metadata_when_loading_then_metadata_buses_and_devices_are_parsed(self):
        """Test loading config from YAML with metadata"""
        yaml_str = """
_metadata:
  generation: 5
  config_source: cloud
  last_modified: "2025-02-14T10:30:45Z"
  checksum: "sha256:abc123"

buses:
  rtu0:
    port: /dev/ttyUSB0
    baudrate: 9600
    timeout: 1.0

devices:
  - model: ADTEK_CPM10
    type: power_meter
    model_file: driver/adtek_cpm_10.yml
    bus: rtu0
    slave_id: 1
"""
        data = yaml.safe_load(yaml_str)
        config = ModbusDeviceFileConfig.model_validate(data)

        # Check metadata
        assert config.metadata.generation == 5
        assert config.metadata.config_source == ConfigSource.CLOUD
        assert config.metadata.last_modified == "2025-02-14T10:30:45Z"
        assert config.metadata.checksum == "sha256:abc123"

        # Check buses
        assert "rtu0" in config.bus_dict
        assert config.bus_dict["rtu0"].port == "/dev/ttyUSB0"
        assert config.bus_dict["rtu0"].baudrate == 9600

        # Check devices
        assert len(config.device_list) == 1
        assert config.device_list[0].model == "ADTEK_CPM10"
        assert config.device_list[0].slave_id == 1
        assert config.device_list[0].bus == "rtu0"

    def test_given_yaml_without_metadata_when_loading_then_default_metadata_is_applied(self):
        """Test loading config without metadata (should use defaults)"""
        yaml_str = """
buses:
  rtu0:
    port: /dev/ttyUSB0
    baudrate: 9600

devices:
  - model: TECO_VFD
    type: vfd
    model_file: driver/teco_vfd.yml
    bus: rtu0
    slave_id: 2
"""
        data = yaml.safe_load(yaml_str)
        config = ModbusDeviceFileConfig.model_validate(data)

        # Should have default metadata
        assert config.metadata.generation == 1
        assert config.metadata.config_source == ConfigSource.EDGE
        assert config.metadata.last_modified is not None

    def test_given_config_object_when_serializing_then_yaml_contains_metadata_buses_and_devices(self):
        """Test serializing config back to YAML with metadata"""
        config = ModbusDeviceFileConfig(
            metadata=ConfigMetadata(generation=3, config_source=ConfigSource.EDGE),
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

        # Serialize with aliases
        data_dict = config.model_dump(by_alias=True, mode="json")

        # Check that _metadata is present
        assert "_metadata" in data_dict
        assert data_dict["_metadata"]["generation"] == 3
        assert data_dict["_metadata"]["config_source"] == "edge"

        # Check that buses and devices are present with correct aliases
        assert "buses" in data_dict
        assert "devices" in data_dict
        assert "rtu0" in data_dict["buses"]
        assert len(data_dict["devices"]) == 1

        # Convert to YAML and verify it's valid
        yaml_str = yaml.dump(data_dict, sort_keys=False, allow_unicode=True)
        assert "_metadata:" in yaml_str
        assert "buses:" in yaml_str
        assert "devices:" in yaml_str

    def test_given_device_with_bus_reference_when_resolving_then_bus_settings_are_merged_into_device(self):
        """Test device bus resolution"""
        config = ModbusDeviceFileConfig(
            bus_dict={"rtu0": ModbusBusConfig(port="/dev/ttyUSB0", baudrate=9600, timeout=1.0)},
            device_list=[
                ModbusDeviceConfig(model="DEVICE1", type="test", model_file="test.yml", bus="rtu0", slave_id=1)
            ],
        )

        resolved = config.resolve_device_bus_settings()
        assert len(resolved) == 1
        assert resolved[0].port == "/dev/ttyUSB0"
        assert resolved[0].baudrate == 9600
        assert resolved[0].timeout == 1.0


class TestConstraintConfigSchema:
    """Test ConstraintConfigSchema with metadata"""

    def test_given_yaml_with_metadata_when_loading_then_metadata_and_device_configs_are_parsed(self):
        """Test loading device instance config with metadata"""
        yaml_str = """
_metadata:
  generation: 2
  config_source: edge
  last_modified: "2025-02-14T11:00:00Z"

version: "1.0.0"

global_defaults:
  initialization:
    startup_frequency: 50.0

TECO_VFD:
  initialization:
    startup_frequency: 50.0
  default_constraints:
    RW_HZ:
      min: 35
      max: 60
  instances: {}

ADAM-4117:
  default_constraints: {}
  instances:
    "12": {}
    "14":
      pins:
        AIn01:
          formula: [0, 5, -1]
"""
        data = yaml.safe_load(yaml_str)
        config = ConstraintConfigSchema.model_validate(data)

        # Check metadata
        assert config.metadata.generation == 2
        assert config.metadata.config_source == ConfigSource.EDGE
        assert config.metadata.last_modified == "2025-02-14T11:00:00Z"

        # Check global_defaults
        assert config.global_defaults is not None
        assert config.global_defaults.initialization.startup_frequency == 50.0

        # Check devices
        assert "TECO_VFD" in config.devices
        assert "ADAM-4117" in config.devices

        # Check TECO_VFD
        teco = config.devices["TECO_VFD"]
        assert teco.initialization.startup_frequency == 50.0
        assert "RW_HZ" in teco.default_constraints
        assert teco.default_constraints["RW_HZ"].min == 35
        assert teco.default_constraints["RW_HZ"].max == 60

        # Check ADAM-4117
        adam = config.devices["ADAM-4117"]
        assert "12" in adam.instances
        assert "14" in adam.instances
        assert adam.instances["14"].pins["AIn01"]["formula"] == [0, 5, -1]

    def test_given_yaml_without_metadata_when_loading_then_default_metadata_is_applied(self):
        """Test loading without metadata uses defaults"""
        yaml_str = """
global_defaults:
  initialization:
    startup_frequency: 50.0

TECO_VFD:
  instances: {}
"""
        data = yaml.safe_load(yaml_str)
        config = ConstraintConfigSchema.model_validate(data)

        # Should have default metadata
        assert config.metadata.generation == 1
        assert config.metadata.config_source == ConfigSource.EDGE

    def test_given_constraint_config_object_when_serializing_then_metadata_and_structure_are_included(self):
        """Test serializing device instance config with metadata"""
        config = ConstraintConfigSchema(
            metadata=ConfigMetadata(generation=4, config_source=ConfigSource.CLOUD),
            global_defaults=DeviceConfig(initialization=InitializationConfig(startup_frequency=50.0)),
            devices={
                "TECO_VFD": DeviceConfig(initialization=InitializationConfig(startup_frequency=50.0), instances={})
            },
        )

        data_dict = config.model_dump(by_alias=True, mode="json")

        # Check metadata
        assert "_metadata" in data_dict
        assert data_dict["_metadata"]["generation"] == 4
        assert data_dict["_metadata"]["config_source"] == "cloud"

        # Check structure
        assert "global_defaults" in data_dict
        assert "devices" in data_dict
        assert "TECO_VFD" in data_dict["devices"]


class TestRoundTripSerialization:
    """Test full round-trip: YAML -> Pydantic -> YAML"""

    def test_given_modbus_device_yaml_when_roundtripping_then_key_elements_are_preserved(self):
        """Test modbus_device config roundtrip"""
        original_yaml = """
_metadata:
  generation: 7
  config_source: edge
  last_modified: "2025-02-14T12:00:00Z"
  last_modified_by: jeremy@example.com
  checksum: sha256:test123

buses:
  rtu0:
    port: /dev/ttyUSB0
    baudrate: 9600
    timeout: 1.0

devices:
  - model: ADTEK_CPM10
    type: power_meter
    model_file: driver/adtek_cpm_10.yml
    bus: rtu0
    slave_id: 1
    modes: {}
"""
        # Load
        data = yaml.safe_load(original_yaml)
        config = ModbusDeviceFileConfig.model_validate(data)

        # Verify loaded correctly
        assert config.metadata.generation == 7
        assert config.metadata.last_modified_by == "jeremy@example.com"

        # Serialize back using mode=json to get proper field names
        output_dict = config.model_dump(by_alias=True, mode="json")
        output_yaml = yaml.dump(output_dict, sort_keys=False, allow_unicode=True)

        # Verify key elements are present
        assert "_metadata:" in output_yaml
        assert "generation: 7" in output_yaml
        assert "buses:" in output_yaml
        assert "devices:" in output_yaml
        assert "ADTEK_CPM10" in output_yaml


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
