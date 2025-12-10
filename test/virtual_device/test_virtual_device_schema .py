import pytest
from pydantic import ValidationError

from core.schema.virtual_device_schema import (
    AggregatedFieldConfig,
    AggregationConfig,
    AggregationMethod,
    ErrorHandling,
    SourceConfig,
    TargetConfig,
    VirtualDeviceConfig,
    VirtualDevicesConfigSchema,
)


class TestAggregatedFieldConfig:
    def test_when_valid_field_config_then_creates_successfully(self):
        # Arrange & Act
        field = AggregatedFieldConfig(name="Kw", method=AggregationMethod.SUM)

        # Assert
        assert field.name == "Kw"
        assert field.method == "sum"

    def test_when_calculated_pf_method_then_creates_successfully(self):
        # Arrange & Act
        field = AggregatedFieldConfig(name="AveragePowerFactor", method=AggregationMethod.CALCULATED_PF)

        # Assert
        assert field.name == "AveragePowerFactor"
        assert field.method == "calculated_pf"


class TestSourceConfig:
    def test_when_no_slave_ids_specified_then_defaults_to_none(self):
        # Arrange & Act
        source = SourceConfig(model="ADTEK_CPM10")

        # Assert
        assert source.model == "ADTEK_CPM10"
        assert source.slave_ids is None

    def test_when_empty_slave_ids_list_then_accepts(self):
        # Arrange & Act
        source = SourceConfig(model="ADTEK_CPM10", slave_ids=[])

        # Assert
        assert source.slave_ids == []

    def test_when_explicit_slave_ids_then_stores_correctly(self):
        # Arrange & Act
        source = SourceConfig(model="ADTEK_CPM10", slave_ids=[1, 2])

        # Assert
        assert source.slave_ids == [1, 2]

    def test_when_negative_slave_id_then_raises_error(self):
        # Arrange & Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            SourceConfig(model="ADTEK_CPM10", slave_ids=[1, -1])

        assert "slave_id must be positive integer" in str(exc_info.value)

    def test_when_zero_slave_id_then_raises_error(self):
        # Arrange & Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            SourceConfig(model="ADTEK_CPM10", slave_ids=[0])

        assert "slave_id must be positive integer" in str(exc_info.value)


class TestTargetConfig:
    def test_when_auto_slave_id_then_accepts(self):
        # Arrange & Act
        target = TargetConfig(model="ADTEK_CPM10", slave_id="auto")

        # Assert
        assert target.slave_id == "auto"

    def test_when_explicit_slave_id_then_accepts(self):
        # Arrange & Act
        target = TargetConfig(model="ADTEK_CPM10", slave_id=11)

        # Assert
        assert target.slave_id == 11

    def test_when_invalid_string_slave_id_then_raises_error(self):
        # Arrange & Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            TargetConfig(model="ADTEK_CPM10", slave_id="invalid")

        assert "slave_id string must be 'auto'" in str(exc_info.value)

    def test_when_negative_slave_id_then_raises_error(self):
        # Arrange & Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            TargetConfig(model="ADTEK_CPM10", slave_id=-1)

        assert "slave_id must be positive integer" in str(exc_info.value)

    def test_when_zero_slave_id_then_raises_error(self):
        # Arrange & Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            TargetConfig(model="ADTEK_CPM10", slave_id=0)

        assert "slave_id must be positive integer" in str(exc_info.value)


class TestAggregationConfig:
    def test_when_valid_aggregation_config_then_creates_successfully(self):
        # Arrange & Act
        agg = AggregationConfig(
            error_handling=ErrorHandling.FAIL_FAST,
            fields=[
                AggregatedFieldConfig(name="Kw", method=AggregationMethod.SUM),
                AggregatedFieldConfig(name="AverageVoltage", method=AggregationMethod.AVG),
            ],
        )

        # Assert
        assert agg.error_handling == "fail_fast"
        assert len(agg.fields) == 2
        assert agg.fields[0].name == "Kw"
        assert agg.fields[1].method == "average"

    def test_when_empty_fields_list_then_raises_error(self):
        # Arrange & Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            AggregationConfig(error_handling=ErrorHandling.FAIL_FAST, fields=[])

        assert "fields cannot be empty" in str(exc_info.value)

    def test_when_error_handling_defaults_to_fail_fast(self):
        # Arrange & Act
        agg = AggregationConfig(fields=[AggregatedFieldConfig(name="Kw", method=AggregationMethod.SUM)])

        # Assert
        assert agg.error_handling == "fail_fast"


class TestVirtualDeviceConfig:
    def test_when_valid_virtual_device_config_then_creates_successfully(self):
        # Arrange & Act
        vdev = VirtualDeviceConfig(
            id="loop0_power_summary",
            enabled=True,
            description="Test virtual device",
            type="aggregated_power_meter",
            source=SourceConfig(model="ADTEK_CPM10", slave_ids=[1, 2]),
            target=TargetConfig(model="ADTEK_CPM10", slave_id="auto"),
            aggregation=AggregationConfig(
                fields=[
                    AggregatedFieldConfig(name="Kw", method=AggregationMethod.SUM),
                ]
            ),
        )

        # Assert
        assert vdev.id == "loop0_power_summary"
        assert vdev.enabled is True
        assert vdev.type == "aggregated_power_meter"
        assert vdev.source.model == "ADTEK_CPM10"
        assert vdev.target.slave_id == "auto"

    def test_when_enabled_defaults_to_true(self):
        # Arrange & Act
        vdev = VirtualDeviceConfig(
            id="test",
            type="aggregated_power_meter",
            source=SourceConfig(model="ADTEK_CPM10"),
            target=TargetConfig(model="ADTEK_CPM10", slave_id="auto"),
            aggregation=AggregationConfig(fields=[AggregatedFieldConfig(name="Kw", method=AggregationMethod.SUM)]),
        )

        # Assert
        assert vdev.enabled is True


class TestVirtualDevicesConfigSchema:
    def test_when_valid_config_then_creates_successfully(self):
        # Arrange
        config_dict = {
            "version": "1.0.0",
            "virtual_devices": [
                {
                    "id": "loop0_power_summary",
                    "enabled": True,
                    "type": "aggregated_power_meter",
                    "source": {"model": "ADTEK_CPM10", "slave_ids": [1, 2]},
                    "target": {"model": "ADTEK_CPM10", "slave_id": "auto"},
                    "aggregation": {
                        "error_handling": "fail_fast",
                        "fields": [{"name": "Kw", "method": "sum"}, {"name": "AverageVoltage", "method": "average"}],
                    },
                }
            ],
        }

        # Act
        config = VirtualDevicesConfigSchema(**config_dict)

        # Assert
        assert config.version == "1.0.0"
        assert len(config.virtual_devices) == 1
        assert config.virtual_devices[0].id == "loop0_power_summary"

    def test_when_empty_virtual_devices_list_then_creates_successfully(self):
        # Arrange & Act
        config = VirtualDevicesConfigSchema(version="1.0.0", virtual_devices=[])

        # Assert
        assert config.version == "1.0.0"
        assert len(config.virtual_devices) == 0

    def test_when_duplicate_virtual_device_ids_then_raises_error(self):
        # Arrange
        config_dict = {
            "version": "1.0.0",
            "virtual_devices": [
                {
                    "id": "duplicate_id",
                    "type": "aggregated_power_meter",
                    "source": {"model": "ADTEK_CPM10"},
                    "target": {"model": "ADTEK_CPM10", "slave_id": "auto"},
                    "aggregation": {"fields": [{"name": "Kw", "method": "sum"}]},
                },
                {
                    "id": "duplicate_id",
                    "type": "aggregated_power_meter",
                    "source": {"model": "ADTEK_CPM10"},
                    "target": {"model": "ADTEK_CPM10", "slave_id": "auto"},
                    "aggregation": {"fields": [{"name": "Kw", "method": "sum"}]},
                },
            ],
        }

        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            VirtualDevicesConfigSchema(**config_dict)

        assert "Duplicate virtual device IDs" in str(exc_info.value)

    def test_when_version_defaults_to_1_0_0(self):
        # Arrange & Act
        config = VirtualDevicesConfigSchema(virtual_devices=[])

        # Assert
        assert config.version == "1.0.0"

    def test_when_loading_from_yaml_structure_then_parses_correctly(self):
        # Arrange - This simulates loading from YAML
        config_dict = {
            "virtual_devices": [
                {
                    "id": "loop0_power_summary",
                    "enabled": True,
                    "description": "Loop0 aggregated power meter",
                    "type": "aggregated_power_meter",
                    "source": {"model": "ADTEK_CPM10"},  # No slave_ids = all devices
                    "target": {"model": "ADTEK_CPM10", "slave_id": "auto"},
                    "aggregation": {
                        "error_handling": "fail_fast",
                        "fields": [
                            {"name": "AverageVoltage", "method": "average"},
                            {"name": "AverageCurrent", "method": "sum"},
                            {"name": "Phase_A_Current", "method": "sum"},
                            {"name": "Phase_B_Current", "method": "sum"},
                            {"name": "Phase_C_Current", "method": "sum"},
                            {"name": "Kw", "method": "sum"},
                            {"name": "Kvar", "method": "sum"},
                            {"name": "Kva", "method": "sum"},
                            {"name": "Kwh_SUM", "method": "sum"},
                            {"name": "Kvarh_SUM", "method": "sum"},
                            {"name": "AveragePowerFactor", "method": "calculated_pf"},
                        ],
                    },
                }
            ]
        }

        # Act
        config = VirtualDevicesConfigSchema(**config_dict)

        # Assert
        assert len(config.virtual_devices) == 1
        vdev = config.virtual_devices[0]
        assert vdev.id == "loop0_power_summary"
        assert vdev.source.slave_ids is None  # No slave_ids = all devices
        assert len(vdev.aggregation.fields) == 11
        assert vdev.aggregation.fields[-1].method == "calculated_pf"
