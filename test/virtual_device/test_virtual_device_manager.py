"""
Unit tests for VirtualDeviceManager

Tests all aggregation logic, error handling, and edge cases.
"""

from datetime import datetime
from unittest.mock import Mock

import pytest

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
from core.util.virtual_device_manager import VirtualDeviceManager


class TestVirtualDeviceManager:
    """Test VirtualDeviceManager core functionality"""

    @pytest.fixture
    def mock_device_manager(self):
        """Create mock AsyncDeviceManager"""
        manager = Mock()
        # Mock device_list with some devices
        device1 = Mock()
        device1.model = "ADTEK_CPM10"
        device1.slave_id = 1

        device2 = Mock()
        device2.model = "ADTEK_CPM10"
        device2.slave_id = 2

        device3 = Mock()
        device3.model = "DAE_PM210"
        device3.slave_id = 5

        manager.device_list = [device1, device2, device3]
        return manager

    @pytest.fixture
    def simple_config(self):
        """Create simple virtual device configuration"""
        return VirtualDevicesConfigSchema(
            virtual_devices=[
                VirtualDeviceConfig(
                    id="test_virtual_device",
                    enabled=True,
                    type="aggregated_power_meter",
                    source=SourceConfig(model="ADTEK_CPM10", slave_ids=None),
                    target=TargetConfig(model="ADTEK_CPM10", slave_id="auto"),
                    aggregation=AggregationConfig(
                        error_handling=ErrorHandling.FAIL_FAST,
                        fields=[
                            AggregatedFieldConfig(name="Kw", method=AggregationMethod.SUM),
                            AggregatedFieldConfig(name="AverageVoltage", method=AggregationMethod.AVG),
                        ],
                    ),
                )
            ]
        )

    def test_when_initialized_then_registers_enabled_devices(self, simple_config, mock_device_manager):
        # Arrange & Act
        manager = VirtualDeviceManager(simple_config, mock_device_manager)

        # Assert
        assert len(manager.enabled_devices) == 1
        assert manager.enabled_devices[0].id == "test_virtual_device"

    def test_when_no_enabled_devices_then_returns_empty(self, mock_device_manager):
        # Arrange
        config = VirtualDevicesConfigSchema(virtual_devices=[])
        manager = VirtualDeviceManager(config, mock_device_manager)
        raw_snapshots = {}

        # Act
        result = manager.compute_virtual_snapshots(raw_snapshots)

        # Assert
        assert not result

    def test_when_all_sources_valid_and_sum_then_aggregates_correctly(self, simple_config, mock_device_manager):
        # Arrange
        manager = VirtualDeviceManager(simple_config, mock_device_manager)

        ts1 = datetime(2024, 12, 9, 12, 0, 0)
        ts2 = datetime(2024, 12, 9, 12, 0, 1)

        raw_snapshots = {
            "ADTEK_CPM10_1": {
                "device_id": "ADTEK_CPM10_1",
                "model": "ADTEK_CPM10",
                "slave_id": 1,
                "sampling_datetime": ts1,
                "values": {"Kw": 100.0, "AverageVoltage": 220.0},
            },
            "ADTEK_CPM10_2": {
                "device_id": "ADTEK_CPM10_2",
                "model": "ADTEK_CPM10",
                "slave_id": 2,
                "sampling_datetime": ts2,
                "values": {"Kw": 150.0, "AverageVoltage": 230.0},
            },
        }

        # Act
        result = manager.compute_virtual_snapshots(raw_snapshots)

        # Assert
        assert len(result) == 1
        virtual_device = result["ADTEK_CPM10_6"]

        assert virtual_device["device_id"] == "ADTEK_CPM10_6"
        assert virtual_device["model"] == "ADTEK_CPM10"
        assert virtual_device["slave_id"] == 6

    def test_when_all_sources_valid_and_avg_then_averages_correctly(self, simple_config, mock_device_manager):
        # Arrange
        manager = VirtualDeviceManager(simple_config, mock_device_manager)

        raw_snapshots = {
            "ADTEK_CPM10_1": {
                "device_id": "ADTEK_CPM10_1",
                "values": {"Kw": 100.0, "AverageVoltage": 220.0},
                "sampling_datetime": datetime.now(),
            },
            "ADTEK_CPM10_2": {
                "device_id": "ADTEK_CPM10_2",
                "values": {"Kw": 150.0, "AverageVoltage": 230.0},
                "sampling_datetime": datetime.now(),
            },
        }

        # Act
        result = manager.compute_virtual_snapshots(raw_snapshots)

        # Assert
        virtual_device = list(result.values())[0]
        assert virtual_device["values"]["Kw"] == 250.0  # sum
        assert virtual_device["values"]["AverageVoltage"] == 225.0  # avg: (220+230)/2

    def test_when_one_source_fails_and_fail_fast_then_returns_negative_one(self, simple_config, mock_device_manager):
        # Arrange
        manager = VirtualDeviceManager(simple_config, mock_device_manager)

        raw_snapshots = {
            "ADTEK_CPM10_1": {
                "device_id": "ADTEK_CPM10_1",
                "values": {"Kw": 100.0, "AverageVoltage": 220.0},
                "sampling_datetime": datetime.now(),
            },
            "ADTEK_CPM10_2": {
                "device_id": "ADTEK_CPM10_2",
                "values": {"Kw": -1, "AverageVoltage": 230.0},  # Kw failed
                "sampling_datetime": datetime.now(),
            },
        }

        # Act
        result = manager.compute_virtual_snapshots(raw_snapshots)

        # Assert
        virtual_device = list(result.values())[0]
        assert virtual_device["values"]["Kw"] == -1  # failed due to fail_fast
        assert virtual_device["values"]["AverageVoltage"] == 225.0  # still ok

    def test_when_no_source_devices_found_then_returns_empty(self, simple_config, mock_device_manager):
        # Arrange
        manager = VirtualDeviceManager(simple_config, mock_device_manager)

        raw_snapshots = {
            "DAE_PM210_5": {  # Different model, not ADTEK_CPM10
                "device_id": "DAE_PM210_5",
                "values": {"Kw": 100.0},
                "sampling_datetime": datetime.now(),
            }
        }

        # Act
        result = manager.compute_virtual_snapshots(raw_snapshots)

        # Assert
        assert not result

    def test_when_explicit_slave_ids_specified_then_filters_correctly(self, mock_device_manager):
        # Arrange
        config = VirtualDevicesConfigSchema(
            virtual_devices=[
                VirtualDeviceConfig(
                    id="test",
                    type="aggregated_power_meter",
                    source=SourceConfig(model="ADTEK_CPM10", slave_ids=[1]),  # Only slave 1
                    target=TargetConfig(model="ADTEK_CPM10", slave_id="auto"),
                    aggregation=AggregationConfig(
                        fields=[AggregatedFieldConfig(name="Kw", method=AggregationMethod.SUM)]
                    ),
                )
            ]
        )
        manager = VirtualDeviceManager(config, mock_device_manager)

        raw_snapshots = {
            "ADTEK_CPM10_1": {
                "device_id": "ADTEK_CPM10_1",
                "values": {"Kw": 100.0},
                "sampling_datetime": datetime.now(),
            },
            "ADTEK_CPM10_2": {
                "device_id": "ADTEK_CPM10_2",
                "values": {"Kw": 150.0},
                "sampling_datetime": datetime.now(),
            },
        }

        # Act
        result = manager.compute_virtual_snapshots(raw_snapshots)

        # Assert
        virtual_device = list(result.values())[0]
        assert virtual_device["values"]["Kw"] == 100.0  # Only slave 1
        assert virtual_device["_source_device_ids"] == ["ADTEK_CPM10_1"]

    def test_when_empty_slave_ids_list_then_aggregates_all(self, mock_device_manager):
        # Arrange
        config = VirtualDevicesConfigSchema(
            virtual_devices=[
                VirtualDeviceConfig(
                    id="test",
                    type="aggregated_power_meter",
                    source=SourceConfig(model="ADTEK_CPM10", slave_ids=[]),  # Empty = all
                    target=TargetConfig(model="ADTEK_CPM10", slave_id="auto"),
                    aggregation=AggregationConfig(
                        fields=[AggregatedFieldConfig(name="Kw", method=AggregationMethod.SUM)]
                    ),
                )
            ]
        )
        manager = VirtualDeviceManager(config, mock_device_manager)

        raw_snapshots = {
            "ADTEK_CPM10_1": {
                "device_id": "ADTEK_CPM10_1",
                "values": {"Kw": 100.0},
                "sampling_datetime": datetime.now(),
            },
            "ADTEK_CPM10_2": {
                "device_id": "ADTEK_CPM10_2",
                "values": {"Kw": 150.0},
                "sampling_datetime": datetime.now(),
            },
        }

        # Act
        result = manager.compute_virtual_snapshots(raw_snapshots)

        # Assert
        virtual_device = list(result.values())[0]
        assert virtual_device["values"]["Kw"] == 250.0  # Both devices

    def test_when_explicit_slave_id_then_uses_that_value(self, mock_device_manager):
        # Arrange
        config = VirtualDevicesConfigSchema(
            virtual_devices=[
                VirtualDeviceConfig(
                    id="test",
                    type="aggregated_power_meter",
                    source=SourceConfig(model="ADTEK_CPM10"),
                    target=TargetConfig(model="ADTEK_CPM10", slave_id=99),  # Explicit
                    aggregation=AggregationConfig(
                        fields=[AggregatedFieldConfig(name="Kw", method=AggregationMethod.SUM)]
                    ),
                )
            ]
        )
        manager = VirtualDeviceManager(config, mock_device_manager)

        raw_snapshots = {
            "ADTEK_CPM10_1": {
                "device_id": "ADTEK_CPM10_1",
                "values": {"Kw": 100.0},
                "sampling_datetime": datetime.now(),
            }
        }

        # Act
        result = manager.compute_virtual_snapshots(raw_snapshots)

        # Assert
        assert "ADTEK_CPM10_99" in result
        assert result["ADTEK_CPM10_99"]["slave_id"] == 99

    def test_when_calculate_power_factor_then_uses_aggregated_kw_kva(self, mock_device_manager):
        # Arrange
        config = VirtualDevicesConfigSchema(
            virtual_devices=[
                VirtualDeviceConfig(
                    id="test",
                    type="aggregated_power_meter",
                    source=SourceConfig(model="ADTEK_CPM10"),
                    target=TargetConfig(model="ADTEK_CPM10", slave_id="auto"),
                    aggregation=AggregationConfig(
                        fields=[
                            AggregatedFieldConfig(name="Kw", method=AggregationMethod.SUM),
                            AggregatedFieldConfig(name="Kva", method=AggregationMethod.SUM),
                            AggregatedFieldConfig(name="AveragePowerFactor", method=AggregationMethod.CALCULATED_PF),
                        ]
                    ),
                )
            ]
        )
        manager = VirtualDeviceManager(config, mock_device_manager)

        raw_snapshots = {
            "ADTEK_CPM10_1": {
                "device_id": "ADTEK_CPM10_1",
                "values": {"Kw": 100.0, "Kva": 120.0},
                "sampling_datetime": datetime.now(),
            },
            "ADTEK_CPM10_2": {
                "device_id": "ADTEK_CPM10_2",
                "values": {"Kw": 150.0, "Kva": 180.0},
                "sampling_datetime": datetime.now(),
            },
        }

        # Act
        result = manager.compute_virtual_snapshots(raw_snapshots)

        # Assert
        virtual_device = list(result.values())[0]
        assert virtual_device["values"]["Kw"] == 250.0
        assert virtual_device["values"]["Kva"] == 300.0
        assert abs(virtual_device["values"]["AveragePowerFactor"] - (250 / 300)) < 0.001  # 0.833...

    def test_when_kva_zero_then_power_factor_returns_zero(self, mock_device_manager):
        # Arrange
        config = VirtualDevicesConfigSchema(
            virtual_devices=[
                VirtualDeviceConfig(
                    id="test",
                    type="aggregated_power_meter",
                    source=SourceConfig(model="ADTEK_CPM10"),
                    target=TargetConfig(model="ADTEK_CPM10", slave_id="auto"),
                    aggregation=AggregationConfig(
                        fields=[
                            AggregatedFieldConfig(name="Kw", method=AggregationMethod.SUM),
                            AggregatedFieldConfig(name="Kva", method=AggregationMethod.SUM),
                            AggregatedFieldConfig(name="AveragePowerFactor", method=AggregationMethod.CALCULATED_PF),
                        ]
                    ),
                )
            ]
        )
        manager = VirtualDeviceManager(config, mock_device_manager)

        raw_snapshots = {
            "ADTEK_CPM10_1": {
                "device_id": "ADTEK_CPM10_1",
                "values": {"Kw": 100.0, "Kva": 0.0},  # Kva = 0
                "sampling_datetime": datetime.now(),
            }
        }

        # Act
        result = manager.compute_virtual_snapshots(raw_snapshots)

        # Assert
        virtual_device = list(result.values())[0]
        assert virtual_device["values"]["AveragePowerFactor"] == 0  # Division by zero handled

    def test_when_kw_or_kva_failed_then_power_factor_returns_negative_one(self, mock_device_manager):
        # Arrange
        config = VirtualDevicesConfigSchema(
            virtual_devices=[
                VirtualDeviceConfig(
                    id="test",
                    type="aggregated_power_meter",
                    source=SourceConfig(model="ADTEK_CPM10"),
                    target=TargetConfig(model="ADTEK_CPM10", slave_id="auto"),
                    aggregation=AggregationConfig(
                        error_handling=ErrorHandling.FAIL_FAST,
                        fields=[
                            AggregatedFieldConfig(name="Kw", method=AggregationMethod.SUM),
                            AggregatedFieldConfig(name="Kva", method=AggregationMethod.SUM),
                            AggregatedFieldConfig(name="AveragePowerFactor", method=AggregationMethod.CALCULATED_PF),
                        ],
                    ),
                )
            ]
        )
        manager = VirtualDeviceManager(config, mock_device_manager)

        raw_snapshots = {
            "ADTEK_CPM10_1": {
                "device_id": "ADTEK_CPM10_1",
                "values": {"Kw": -1, "Kva": 120.0},  # Kw failed
                "sampling_datetime": datetime.now(),
            }
        }

        # Act
        result = manager.compute_virtual_snapshots(raw_snapshots)

        # Assert
        virtual_device = list(result.values())[0]
        assert virtual_device["values"]["Kw"] == -1
        assert virtual_device["values"]["AveragePowerFactor"] == -1  # Cannot calculate

    def test_when_sampling_datetime_differs_then_uses_latest(self, simple_config, mock_device_manager):
        # Arrange
        manager = VirtualDeviceManager(simple_config, mock_device_manager)

        ts1 = datetime(2024, 12, 9, 12, 0, 0)
        ts2 = datetime(2024, 12, 9, 12, 0, 5)  # 5 seconds later

        raw_snapshots = {
            "ADTEK_CPM10_1": {
                "device_id": "ADTEK_CPM10_1",
                "values": {"Kw": 100.0, "AverageVoltage": 220.0},
                "sampling_datetime": ts1,
            },
            "ADTEK_CPM10_2": {
                "device_id": "ADTEK_CPM10_2",
                "values": {"Kw": 150.0, "AverageVoltage": 230.0},
                "sampling_datetime": ts2,
            },
        }

        # Act
        result = manager.compute_virtual_snapshots(raw_snapshots)

        # Assert
        virtual_device = list(result.values())[0]
        assert virtual_device["sampling_datetime"] == ts2  # Latest timestamp

    def test_when_virtual_device_in_snapshots_then_skips_it(self, simple_config, mock_device_manager):
        # Arrange
        manager = VirtualDeviceManager(simple_config, mock_device_manager)

        raw_snapshots = {
            "ADTEK_CPM10_1": {
                "device_id": "ADTEK_CPM10_1",
                "values": {"Kw": 100.0, "AverageVoltage": 220.0},
                "sampling_datetime": datetime.now(),
            },
            "ADTEK_CPM10_999": {  # Another virtual device
                "device_id": "ADTEK_CPM10_999",
                "values": {"Kw": 999.0, "AverageVoltage": 999.0},
                "sampling_datetime": datetime.now(),
                "_is_virtual": True,  # Marked as virtual
            },
        }

        # Act
        result = manager.compute_virtual_snapshots(raw_snapshots)

        # Assert
        virtual_device = list(result.values())[0]
        assert virtual_device["values"]["Kw"] == 100.0  # Only from device 1
        assert len(virtual_device["_source_device_ids"]) == 1

    def test_when_metadata_included_then_contains_debug_info(self, simple_config, mock_device_manager):
        # Arrange
        manager = VirtualDeviceManager(simple_config, mock_device_manager)

        raw_snapshots = {
            "ADTEK_CPM10_1": {
                "device_id": "ADTEK_CPM10_1",
                "values": {"Kw": 100.0, "AverageVoltage": 220.0},
                "sampling_datetime": datetime.now(),
            }
        }

        # Act
        result = manager.compute_virtual_snapshots(raw_snapshots)

        # Assert
        virtual_device = list(result.values())[0]
        assert virtual_device["_is_virtual"] is True
        assert virtual_device["_virtual_config_id"] == "test_virtual_device"
        assert virtual_device["_source_device_ids"] == ["ADTEK_CPM10_1"]
        assert "type" in virtual_device
        assert virtual_device["type"] == "power_meter"
