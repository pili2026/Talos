import pytest
from pydantic import ValidationError

from api.model.wifi import WpaNetworkRow, WpaStatus


class TestWpaNetworkRow:
    """Tests for the WpaNetworkRow model"""

    def test_when_valid_data_then_creates_instance(self):
        """Test: instance is created successfully with valid data"""
        row = WpaNetworkRow(
            network_id=0,
            ssid="MyNetwork",
            bssid="00:11:22:33:44:55",
            flags="[CURRENT]",
        )

        assert row.network_id == 0
        assert row.ssid == "MyNetwork"
        assert row.bssid == "00:11:22:33:44:55"
        assert row.flags == "[CURRENT]"

    def test_when_optional_fields_none_then_accepts(self):
        """Test: optional fields accept None values"""
        row = WpaNetworkRow(network_id=1, ssid="Network", bssid=None, flags=None)

        assert row.bssid is None
        assert row.flags is None

    def test_when_missing_required_field_then_validation_error(self):
        """Test: missing required fields raise validation error"""
        with pytest.raises(ValidationError) as exc_info:
            WpaNetworkRow(network_id=0)  # Missing ssid

        errors = exc_info.value.errors()
        assert any(e["loc"] == ("ssid",) for e in errors)

    def test_when_invalid_network_id_type_then_converts_or_fails(self):
        """Test: invalid network_id type is either coerced or rejected"""
        # Pydantic attempts type coercion
        row = WpaNetworkRow(network_id="123", ssid="Test", bssid=None, flags=None)
        assert row.network_id == 123

        # Non-convertible values should fail
        with pytest.raises(ValidationError):
            WpaNetworkRow(network_id="abc", ssid="Test", bssid=None, flags=None)

    def test_when_frozen_then_immutable(self):
        """Test: instances are immutable when frozen=True"""
        row = WpaNetworkRow(network_id=0, ssid="Test", bssid=None, flags=None)

        with pytest.raises(ValidationError):
            row.ssid = "Modified"  # Should fail


class TestWpaStatus:
    """Tests for the WpaStatus model"""

    def test_when_from_wpa_output_with_valid_data_then_parses_correctly(self, sample_wpa_status_output):
        """Test: from_wpa_output correctly parses valid WPA output"""
        status = WpaStatus.from_wpa_output(sample_wpa_status_output)

        assert status.ssid == "MyNetwork"
        assert status.bssid == "00:11:22:33:44:55"
        assert status.freq == 2437
        assert status.wpa_state == "COMPLETED"
        assert status.ip_address == "192.168.1.100"
        assert status.network_id == 0
        assert status.key_mgmt == "WPA2-PSK"

    def test_when_from_wpa_output_with_empty_then_all_none(self):
        """Test: empty output results in all fields being None"""
        status = WpaStatus.from_wpa_output("")

        assert status.ssid is None
        assert status.bssid is None
        assert status.freq is None
        assert status.wpa_state is None
        assert status.ip_address is None
        assert status.network_id is None
        assert status.key_mgmt is None

    def test_when_from_wpa_output_with_partial_data_then_fills_available(self):
        """Test: partial output populates only available fields"""
        partial = "ssid=TestNet\nwpa_state=SCANNING"
        status = WpaStatus.from_wpa_output(partial)

        assert status.ssid == "TestNet"
        assert status.wpa_state == "SCANNING"
        assert status.ip_address is None
        assert status.bssid is None

    def test_when_completed_with_ssid_and_ip_then_is_connected_true(self):
        """Test: COMPLETED + SSID + IP results in is_connected=True"""
        status = WpaStatus(
            ssid="MyNetwork",
            wpa_state="COMPLETED",
            ip_address="192.168.1.100",
        )

        assert status.is_connected is True

    def test_when_completed_without_ip_then_is_connected_false(self):
        """Test: COMPLETED without IP results in is_connected=False"""
        status = WpaStatus(
            ssid="MyNetwork",
            wpa_state="COMPLETED",
            ip_address=None,
        )

        assert status.is_connected is False

    def test_when_not_completed_then_is_connected_false(self):
        """Test: non-COMPLETED state results in is_connected=False"""
        status = WpaStatus(
            ssid="MyNetwork",
            wpa_state="SCANNING",
            ip_address="192.168.1.100",
        )

        assert status.is_connected is False

    def test_when_frozen_then_immutable(self):
        """Test: instances are immutable when frozen=True"""
        status = WpaStatus(ssid="Test")

        with pytest.raises(ValidationError):
            status.ssid = "Modified"
