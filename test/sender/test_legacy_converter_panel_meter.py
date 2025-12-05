"""Tests for panel meter converter (GTA-A26-A)."""

from core.model.device_constant import DEFAULT_MISSING_VALUE
from core.sender.legacy.snapshot_converters import convert_panel_meter_snapshot


class TestConvertPanelMeterSnapshot:
    """Test convert_panel_meter_snapshot() for A26A panel meter."""

    def test_when_normal_values_then_convert_totalize_and_rate(self):
        """Normal case: TOTALIZE and RATE with typical values."""
        values = {
            "TOTALIZE": 12345.67,
            "RATE": 123.4567,
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW123456789AB",
            slave_id="10",
            values=values,
        )

        assert len(result) == 1
        assert result[0]["Data"]["consumption"] == 12345  # int conversion
        assert result[0]["Data"]["flow"] == 123.4567  # rounded to 4 decimals
        assert result[0]["Data"]["revconsumption"] == 0
        assert result[0]["Data"]["direction"] == 0

    def test_when_values_zero_then_output_zero(self):
        """All values are zero."""
        values = {
            "TOTALIZE": 0.0,
            "RATE": 0.0,
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW123456789AB",
            slave_id="10",
            values=values,
        )

        assert len(result) == 1
        assert result[0]["Data"]["consumption"] == 0
        assert result[0]["Data"]["flow"] == 0.0
        assert result[0]["Data"]["revconsumption"] == 0
        assert result[0]["Data"]["direction"] == 0

    def test_when_values_large_then_convert_properly(self):
        """Large values (approaching real-world maximums)."""
        values = {
            "TOTALIZE": 999999999.99,
            "RATE": 99999.9999,
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW123456789AB",
            slave_id="10",
            values=values,
        )

        assert len(result) == 1
        assert result[0]["Data"]["consumption"] == 999999999
        assert result[0]["Data"]["flow"] == 99999.9999

    def test_when_flow_has_more_than_four_decimals_then_round_to_four(self):
        """Flow value is rounded to 4 decimal places."""
        values = {
            "TOTALIZE": 1000.0,
            "RATE": 12.345678901,  # More than 4 decimals
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW123456789AB",
            slave_id="10",
            values=values,
        )

        assert result[0]["Data"]["flow"] == 12.3457  # Rounded to 4 decimals

    def test_when_totalize_has_decimal_then_truncate_to_int(self):
        """Consumption is converted to int (truncates decimal)."""
        values = {
            "TOTALIZE": 12345.999,  # Should truncate to 12345
            "RATE": 1.0,
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW123456789AB",
            slave_id="10",
            values=values,
        )

        assert result[0]["Data"]["consumption"] == 12345
        assert isinstance(result[0]["Data"]["consumption"], int)

    def test_when_totalize_missing_then_return_minus_one(self):
        """Missing TOTALIZE returns -1 (not 0) to indicate read failure."""
        values = {
            "RATE": 123.45,
            # TOTALIZE missing
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW123456789AB",
            slave_id="10",
            values=values,
        )

        assert len(result) == 1
        assert result[0]["Data"]["consumption"] == DEFAULT_MISSING_VALUE  # -1, not 0
        assert result[0]["Data"]["flow"] == round(123.45, 4)
        assert result[0]["DeviceID"] == "GW123456789AB_0A0SF"  # slave_id=10 (0x0A), idx=0, suffix=SF

    def test_when_rate_missing_then_return_minus_one(self):
        """Missing RATE returns -1 (not 0) to indicate read failure."""
        values = {
            "TOTALIZE": 12345.0,
            # RATE missing
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW123456789AB",
            slave_id="10",
            values=values,
        )

        assert len(result) == 1
        assert result[0]["Data"]["consumption"] == 12345
        assert result[0]["Data"]["flow"] == float(DEFAULT_MISSING_VALUE)  # -1.0, not 0.0
        assert result[0]["DeviceID"] == "GW123456789AB_0A0SF"

    def test_when_values_empty_then_return_minus_one_record(self):
        """Empty values dict returns record with -1 (not 0) to indicate read failures."""
        values = {}

        result = convert_panel_meter_snapshot(
            gateway_id="GW123456789AB",
            slave_id="10",
            values=values,
        )

        assert len(result) == 1
        # All values should be -1 to indicate missing data
        assert result[0]["Data"]["consumption"] == DEFAULT_MISSING_VALUE
        assert result[0]["Data"]["flow"] == float(DEFAULT_MISSING_VALUE)
        assert result[0]["Data"]["revconsumption"] == 0  # Always 0 (not a real field)
        assert result[0]["Data"]["direction"] == 0  # Always 0 (not a real field)

    def test_when_values_are_none_then_return_minus_one(self):
        """None values return -1 (not 0) to indicate read failures."""
        values = {
            "TOTALIZE": None,
            "RATE": None,
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW123456789AB",
            slave_id="10",
            values=values,
        )

        assert len(result) == 1
        # None should be treated as missing data (-1), not valid zero
        assert result[0]["Data"]["consumption"] == DEFAULT_MISSING_VALUE
        assert result[0]["Data"]["flow"] == float(DEFAULT_MISSING_VALUE)

    def test_when_values_are_minus_one_string_then_preserve_minus_one(self):
        """Driver returns "-1" string for read failures, should be preserved as -1."""
        values = {
            "TOTALIZE": "-1",
            "RATE": "-1",
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW123456789AB",
            slave_id="10",
            values=values,
        )

        assert len(result) == 1
        # "-1" string should be converted to -1 (not scaled)
        assert result[0]["Data"]["consumption"] == DEFAULT_MISSING_VALUE
        assert result[0]["Data"]["flow"] == float(DEFAULT_MISSING_VALUE)

    def test_when_totalize_zero_then_preserve_zero(self):
        """Actual zero value (not missing) should be preserved as 0."""
        values = {
            "TOTALIZE": 0.0,  # Valid zero, not missing
            "RATE": 100.5,
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW123456789AB",
            slave_id="10",
            values=values,
        )

        assert len(result) == 1
        # Valid zero should remain 0 (distinguishable from -1 failure)
        assert result[0]["Data"]["consumption"] == 0
        assert result[0]["Data"]["flow"] == round(100.5, 4)

    def test_when_rate_zero_then_preserve_zero(self):
        """Actual zero flow rate (not missing) should be preserved as 0.0."""
        values = {
            "TOTALIZE": 5000.0,
            "RATE": 0.0,  # Valid zero, not missing
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW123456789AB",
            slave_id="10",
            values=values,
        )

        assert len(result) == 1
        # Valid zero should remain 0.0 (distinguishable from -1.0 failure)
        assert result[0]["Data"]["consumption"] == 5000
        assert result[0]["Data"]["flow"] == 0.0

    def test_normal_values(self):
        """Normal operation with valid values."""
        values = {
            "TOTALIZE": 12345.67,
            "RATE": 123.4567,
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW123456789AB",
            slave_id="10",
            values=values,
        )

        assert len(result) == 1
        assert result[0]["Data"]["consumption"] == 12345  # int conversion
        assert result[0]["Data"]["flow"] == round(123.4567, 4)  # 123.4567
        assert result[0]["Data"]["revconsumption"] == 0
        assert result[0]["Data"]["direction"] == 0
        assert result[0]["DeviceID"] == "GW123456789AB_0A0SF"

    def test_device_id_format(self):
        """Device ID follows SF (flow meter) format."""
        values = {"TOTALIZE": 100.0, "RATE": 50.0}

        result = convert_panel_meter_snapshot(
            gateway_id="ABC123",
            slave_id="5",
            values=values,
        )

        assert result[0]["DeviceID"] == "ABC123_050SF"

    def test_partial_read_failure_scenario(self):
        """One field succeeds, one fails - both states should be clear."""
        values = {
            "TOTALIZE": 9999.0,  # Success
            "RATE": "-1",  # Failure
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW123456789AB",
            slave_id="10",
            values=values,
        )

        assert len(result) == 1
        assert result[0]["Data"]["consumption"] == 9999  # Valid data
        assert result[0]["Data"]["flow"] == float(DEFAULT_MISSING_VALUE)  # Failed read

    def test_when_generating_device_id_then_append_sf_suffix(self):
        """DeviceID uses SF equipment type suffix."""
        values = {
            "TOTALIZE": 100.0,
            "RATE": 10.0,
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW123456789AB",
            slave_id="10",
            values=values,
        )

        device_id = result[0]["DeviceID"]
        assert device_id.startswith("GW123456789")  # First 11 chars
        assert device_id.endswith("0A0SF")  # slave_id=10 (0x0A), idx=0, suffix=SF

    def test_when_slave_id_is_integer_then_convert_properly(self):
        """DeviceID works with integer slave_id."""
        values = {
            "TOTALIZE": 100.0,
            "RATE": 10.0,
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW123456789AB",
            slave_id=15,  # Integer slave_id
            values=values,
        )

        device_id = result[0]["DeviceID"]
        assert device_id.endswith("0F0SF")  # slave_id=15 (0x0F), idx=0, suffix=SF

    def test_when_slave_id_is_string_then_convert_properly(self):
        """DeviceID works with string slave_id."""
        values = {
            "TOTALIZE": 100.0,
            "RATE": 10.0,
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW123456789AB",
            slave_id="20",  # String slave_id
            values=values,
        )

        device_id = result[0]["DeviceID"]
        assert device_id.endswith("140SF")  # slave_id=20 (0x14), idx=0, suffix=SF

    def test_when_converted_then_include_all_required_fields(self):
        """Data dict contains all flow meter format fields."""
        values = {
            "TOTALIZE": 1234.56,
            "RATE": 12.34,
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW123456789AB",
            slave_id="10",
            values=values,
        )

        data = result[0]["Data"]
        assert set(data.keys()) == {"flow", "consumption", "revconsumption", "direction"}
        assert isinstance(data["flow"], float)
        assert isinstance(data["consumption"], int)
        assert isinstance(data["revconsumption"], int)
        assert isinstance(data["direction"], int)

    def test_when_converted_then_result_structure_valid(self):
        """Result has correct structure."""
        values = {
            "TOTALIZE": 100.0,
            "RATE": 10.0,
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW123456789AB",
            slave_id="10",
            values=values,
        )

        assert isinstance(result, list)
        assert len(result) == 1
        assert "DeviceID" in result[0]
        assert "Data" in result[0]
        assert isinstance(result[0]["DeviceID"], str)
        assert isinstance(result[0]["Data"], dict)

    def test_when_convert_then_revconsumption_and_direction_zero(self):
        """revconsumption and direction are always 0."""
        values = {
            "TOTALIZE": 9999.99,
            "RATE": 999.99,
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW123456789AB",
            slave_id="10",
            values=values,
        )

        assert result[0]["Data"]["revconsumption"] == 0
        assert result[0]["Data"]["direction"] == 0

    def test_when_panel_meter_then_idx_always_zero(self):
        """idx parameter is always 0 for panel meter."""
        values = {
            "TOTALIZE": 100.0,
            "RATE": 10.0,
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW123456789AB",
            slave_id="5",
            values=values,
        )

        # For slave_id=5, idx=0, the DeviceID should end with 050SF
        device_id = result[0]["DeviceID"]
        assert device_id.endswith("050SF")  # slave_id=5 (0x05), idx=0, suffix=SF

    def test_when_values_are_string_then_cast_to_float(self):
        """String values in dict are converted to float."""
        values = {
            "TOTALIZE": "12345.67",  # String instead of float
            "RATE": "123.45",  # String instead of float
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW123456789AB",
            slave_id="10",
            values=values,
        )

        assert result[0]["Data"]["consumption"] == 12345
        assert result[0]["Data"]["flow"] == 123.45


class TestPanelMeterIntegration:
    """Integration tests for panel meter converter."""

    def test_when_real_world_normal_then_convert_correctly(self):
        """Real-world scenario: Normal operation with actual values."""
        values = {
            "TOTALIZE": 76774.0,  # Accumulated consumption
            "RATE": 245.5,  # Current flow rate
            "MAXD": 76774.0,  # Max demand (not used in conversion)
            "DEMAND": 0.0,  # Current demand (not used in conversion)
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW987654321XX",
            slave_id="8",
            values=values,
        )

        assert len(result) == 1
        assert result[0]["Data"]["consumption"] == 76774
        assert result[0]["Data"]["flow"] == 245.5
        assert result[0]["Data"]["revconsumption"] == 0
        assert result[0]["Data"]["direction"] == 0
        assert result[0]["DeviceID"].endswith("080SF")  # slave_id=8 (0x08), idx=0, suffix=SF

    def test_when_real_world_idle_then_flow_zero(self):
        """Real-world scenario: Device idle (no flow)."""
        values = {
            "TOTALIZE": 50000.0,  # Some accumulated value
            "RATE": 0.0,  # No current flow
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW987654321XX",
            slave_id="12",
            values=values,
        )

        assert result[0]["Data"]["consumption"] == 50000
        assert result[0]["Data"]["flow"] == 0.0

    def test_when_device_startup_then_all_zero(self):
        """Real-world scenario: Device just started (all zeros)."""
        values = {
            "TOTALIZE": 0.0,
            "RATE": 0.0,
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW987654321XX",
            slave_id="1",
            values=values,
        )

        assert result[0]["Data"]["consumption"] == 0
        assert result[0]["Data"]["flow"] == 0.0

    def test_when_converted_then_match_flow_meter_format(self):
        """Output format is compatible with flow meter format."""
        values = {
            "TOTALIZE": 1000.0,
            "RATE": 50.5,
        }

        result = convert_panel_meter_snapshot(
            gateway_id="GW123456789AB",
            slave_id="10",
            values=values,
        )

        # Check all fields match flow meter format
        data = result[0]["Data"]
        required_fields = {"flow", "consumption", "revconsumption", "direction"}
        assert set(data.keys()) == required_fields

        # Check data types match flow meter format
        assert isinstance(data["flow"], float)
        assert isinstance(data["consumption"], int)
        assert isinstance(data["revconsumption"], int)
        assert isinstance(data["direction"], int)

        # Check DeviceID uses SF suffix (same as flow meter)
        assert result[0]["DeviceID"].endswith("SF")

    def test_when_multiple_devices_then_each_has_correct_device_id(self):
        """Multiple devices across different gateways."""
        test_cases = [
            ("GW111111111AA", "1", 100.0, 10.0),
            ("GW222222222BB", "5", 200.0, 20.0),
            ("GW333333333CC", "10", 300.0, 30.0),
        ]

        for gateway_id, slave_id, totalize, rate in test_cases:
            values = {
                "TOTALIZE": totalize,
                "RATE": rate,
            }

            result = convert_panel_meter_snapshot(
                gateway_id=gateway_id,
                slave_id=slave_id,
                values=values,
            )

            assert len(result) == 1
            assert result[0]["DeviceID"].startswith(gateway_id[:11])
            assert result[0]["Data"]["consumption"] == int(totalize)
            assert result[0]["Data"]["flow"] == rate
