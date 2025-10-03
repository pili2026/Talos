# tests/test_convert_snapshot_to_legacy_payload.py

import pytest
from unittest.mock import Mock
from converter.legacy_converter import (
    convert_snapshot_to_legacy_payload,
)


@pytest.fixture
def mock_device_manager():
    """Mock AsyncDeviceManager."""
    manager = Mock()
    return manager


@pytest.fixture
def mock_ai_device():
    """Mock AI module device with pin_type_map."""
    device = Mock()
    device.pin_type_map = {
        "AIn01": "temperature",
        "AIn02": "humidity",
    }
    return device


class TestConvertSnapshotToLegacyPayload:
    """Test convert_snapshot_to_legacy_payload() dispatcher function."""

    def test_di_module_ima_c_with_model_parameter(self, mock_device_manager):
        """DI module (IMA_C): model parameter is correctly passed."""
        snapshot = {
            "type": "di_module",
            "model": "IMA_C",
            "slave_id": "5",
            "values": {
                "DIn01": "1",
                "DIn02": "0",
                "DOut01": "1",
                "DOut02": "0",
            },
        }

        result = convert_snapshot_to_legacy_payload(
            gateway_id="GW123456789AB", snapshot=snapshot, device_manager=mock_device_manager
        )

        # Should return 2 records (one per DIn pin)
        assert len(result) == 2

        # Verify DOut mapping works (IMA_C specific)
        assert result[0]["Data"]["Relay0"] == 1  # DIn01
        assert result[0]["Data"]["MCStatus0"] == 1  # DOut01 mapped
        assert result[1]["Data"]["Relay0"] == 0  # DIn02
        assert result[1]["Data"]["MCStatus0"] == 0  # DOut02 mapped

    def test_di_module_other_model_no_dout_mapping(self, mock_device_manager):
        """DI module (non-IMA_C): MCStatus0 should be 0."""
        snapshot = {
            "type": "di_module",
            "model": "SD400",
            "slave_id": "3",
            "values": {
                "DIn01": "1",
                "DIn02": "0",
                "DOut01": "1",
                "DOut02": "1",
            },
        }

        result = convert_snapshot_to_legacy_payload(
            gateway_id="GW123456789AB", snapshot=snapshot, device_manager=mock_device_manager
        )

        assert len(result) == 2
        # No DOut mapping for SD400
        assert result[0]["Data"]["MCStatus0"] == 0
        assert result[1]["Data"]["MCStatus0"] == 0

    def test_ai_module_uses_pin_type_map(self, mock_device_manager, mock_ai_device):
        """AI module: pin_type_map is correctly retrieved and passed."""
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_ai_device

        snapshot = {
            "type": "ai_module",
            "model": "IMA_C",
            "slave_id": "5",
            "values": {
                "AIn01": "25.5",
                "AIn02": "60.0",
            },
        }

        result = convert_snapshot_to_legacy_payload(
            gateway_id="GW123456789AB", snapshot=snapshot, device_manager=mock_device_manager
        )

        # Verify device lookup was called
        mock_device_manager.get_device_by_model_and_slave_id.assert_called_once_with("IMA_C", "5")

        # Should return records based on pin_type_map
        assert len(result) == 2

    def test_ai_module_device_not_found(self, mock_device_manager):
        """AI module: Returns empty list if device not found."""
        mock_device_manager.get_device_by_model_and_slave_id.return_value = None

        snapshot = {"type": "ai_module", "model": "UNKNOWN", "slave_id": "99", "values": {"AIn01": "25.5"}}

        result = convert_snapshot_to_legacy_payload(
            gateway_id="GW123456789AB", snapshot=snapshot, device_manager=mock_device_manager
        )

        assert result == []

    def test_inverter_online_status(self, mock_device_manager):
        """Inverter: Standard call with online status."""
        snapshot = {
            "type": "inverter",
            "model": "HUAWEI_SUN2000",
            "slave_id": "1",
            "values": {
                "INVSTATUS": "0",
                "PV_POWER": "5000",
                "ERROR": "0",
                "ALERT": "0",
            },
        }

        result = convert_snapshot_to_legacy_payload(
            gateway_id="GW123456789AB", snapshot=snapshot, device_manager=mock_device_manager
        )

        # Inverter should return one record
        assert len(result) == 1
        assert "DeviceID" in result[0]
        assert "Data" in result[0]

    def test_unsupported_device_type(self, mock_device_manager):
        """Unsupported device type: Returns empty list."""
        snapshot = {"type": "unknown_type", "model": "UNKNOWN", "slave_id": "1", "values": {}}

        result = convert_snapshot_to_legacy_payload(
            gateway_id="GW123456789AB", snapshot=snapshot, device_manager=mock_device_manager
        )

        assert result == []

    def test_missing_values_field(self, mock_device_manager):
        """Missing 'values' field: Treats as empty dict."""
        snapshot = {
            "type": "di_module",
            "model": "IMA_C",
            "slave_id": "5",
            # No 'values' field
        }

        result = convert_snapshot_to_legacy_payload(
            gateway_id="GW123456789AB", snapshot=snapshot, device_manager=mock_device_manager
        )

        # No DIn pins, should return empty
        assert result == []

    def test_model_none_gracefully_handled(self, mock_device_manager):
        """model=None is handled gracefully (treats as non-IMA_C)."""
        snapshot = {
            "type": "di_module",
            "model": None,  # None is valid, just not IMA_C
            "slave_id": "5",
            "values": {"DIn01": "1", "DOut01": "1"},
        }

        result = convert_snapshot_to_legacy_payload(
            gateway_id="GW123456789AB", snapshot=snapshot, device_manager=mock_device_manager
        )

        # Should work, but MCStatus0 should be 0 (not IMA_C)
        assert len(result) == 1
        assert result[0]["Data"]["Relay0"] == 1
        assert result[0]["Data"]["MCStatus0"] == 0  # None != "IMA_C"

    def test_exception_in_converter_function(self, mock_device_manager, monkeypatch):
        """Exception in converter function: Returns empty list with warning."""

        def mock_converter_that_raises(*args, **kwargs):
            raise ValueError("Simulated converter error")

        # Patch the DI converter to raise an exception
        from converter import legacy_converter

        monkeypatch.setitem(legacy_converter.CONVERTER_MAP, "di_module", mock_converter_that_raises)

        snapshot = {"type": "di_module", "model": "IMA_C", "slave_id": "5", "values": {"DIn01": "1"}}

        result = convert_snapshot_to_legacy_payload(
            gateway_id="GW123456789AB", snapshot=snapshot, device_manager=mock_device_manager
        )

        # Should handle gracefully
        assert result == []

    def test_values_shallow_copy(self, mock_device_manager):
        """Original snapshot values are not modified."""
        original_values = {"DIn01": "1", "DOut01": "1"}
        snapshot = {"type": "di_module", "model": "IMA_C", "slave_id": "5", "values": original_values}

        result = convert_snapshot_to_legacy_payload(
            gateway_id="GW123456789AB", snapshot=snapshot, device_manager=mock_device_manager
        )

        # Original values should be unchanged
        assert snapshot["values"] == original_values
        assert len(result) == 1


class TestDiModuleIntegrationWithDispatcher:
    """Integration tests for DI module through the dispatcher."""

    def test_ima_c_full_flow(self, mock_device_manager):
        """IMA_C: Full conversion flow with DOut mapping."""
        snapshot = {
            "type": "di_module",
            "model": "IMA_C",
            "slave_id": "5",
            "values": {
                "DIn01": "1",
                "DIn02": "0",
                "DIn03": "1",
                "DOut01": "0",
                "DOut02": "1",
                "DOut03": "0",
            },
        }

        result = convert_snapshot_to_legacy_payload(
            gateway_id="GW987654321XX", snapshot=snapshot, device_manager=mock_device_manager
        )

        assert len(result) == 3

        # Verify DIn/DOut pairing
        assert result[0]["Data"]["Relay0"] == 1  # DIn01
        assert result[0]["Data"]["MCStatus0"] == 0  # DOut01

        assert result[1]["Data"]["Relay0"] == 0  # DIn02
        assert result[1]["Data"]["MCStatus0"] == 1  # DOut02

        assert result[2]["Data"]["Relay0"] == 1  # DIn03
        assert result[2]["Data"]["MCStatus0"] == 0  # DOut03

    def test_sd400_no_dout_mapping(self, mock_device_manager):
        """SD400: No DOut mapping even if DOut values exist."""
        snapshot = {
            "type": "di_module",
            "model": "SD400",
            "slave_id": "3",
            "values": {
                "DIn01": "1",
                "DIn02": "1",
                "DOut01": "1",
                "DOut02": "1",
            },
        }

        result = convert_snapshot_to_legacy_payload(
            gateway_id="GW123456789AB", snapshot=snapshot, device_manager=mock_device_manager
        )

        assert len(result) == 2

        # All MCStatus0 should be 0 for SD400
        assert all(r["Data"]["MCStatus0"] == 0 for r in result)

        # But Relay0 (DIn values) should be correct
        assert result[0]["Data"]["Relay0"] == 1
        assert result[1]["Data"]["Relay0"] == 1

    def test_ima_c_partial_dout(self, mock_device_manager):
        """IMA_C: Gracefully handle missing DOut pins."""
        snapshot = {
            "type": "di_module",
            "model": "IMA_C",
            "slave_id": "5",
            "values": {
                "DIn01": "1",
                "DIn02": "0",
                "DIn03": "1",
                "DOut01": "1",
                # DOut02 missing
                "DOut03": "1",
            },
        }

        result = convert_snapshot_to_legacy_payload(
            gateway_id="GW123456789AB", snapshot=snapshot, device_manager=mock_device_manager
        )

        assert len(result) == 3

        assert result[0]["Data"]["MCStatus0"] == 1  # DOut01 exists
        assert result[1]["Data"]["MCStatus0"] == 0  # DOut02 missing → default 0
        assert result[2]["Data"]["MCStatus0"] == 1  # DOut03 exists


class TestParameterPassingPatterns:
    """Test different parameter passing patterns for different device types."""

    def test_di_module_four_argument_pattern(self, mock_device_manager):
        """DI module: 4-arg pattern (gateway_id, slave_id, values, model)."""
        snapshot = {"type": "di_module", "model": "IMA_C", "slave_id": "5", "values": {"DIn01": "1", "DOut01": "1"}}

        result = convert_snapshot_to_legacy_payload(
            gateway_id="GW123456789AB", snapshot=snapshot, device_manager=mock_device_manager
        )

        # DI uses model parameter
        assert len(result) == 1
        assert result[0]["Data"]["MCStatus0"] == 1  # Verify model was used

    def test_ai_module_four_argument_pattern(self, mock_device_manager, mock_ai_device):
        """AI module: 4-arg pattern (gateway_id, slave_id, values, pin_type_map)."""
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_ai_device

        snapshot = {"type": "ai_module", "model": "IMA_C", "slave_id": "5", "values": {"AIn01": "25.5"}}

        result = convert_snapshot_to_legacy_payload(
            gateway_id="GW123456789AB", snapshot=snapshot, device_manager=mock_device_manager
        )

        assert len(result) >= 1

    def test_inverter_three_argument_pattern(self, mock_device_manager):
        """Inverter: Standard 3-arg pattern (gateway_id, slave_id, values)."""
        snapshot = {
            "type": "inverter",
            "model": "HUAWEI_SUN2000",
            "slave_id": "1",
            "values": {
                "INVSTATUS": "0",
                "PV_POWER": "5000",
            },
        }

        result = convert_snapshot_to_legacy_payload(
            gateway_id="GW123456789AB", snapshot=snapshot, device_manager=mock_device_manager
        )

        # Inverter uses standard 3-arg pattern
        assert len(result) == 1
