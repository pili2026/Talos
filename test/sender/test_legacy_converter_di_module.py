#


from sender.legacy.snapshot_converters import _get_do_state_for_di, convert_di_module_snapshot


class TestGetDoStateForDi:
    """Test _get_do_state_for_di() helper function."""

    def test_ima_c_with_matching_dout(self):
        """IMA_C: DOut exists and has valid value."""
        snapshot = {"DOut01": "1", "DOut02": "0"}

        assert _get_do_state_for_di(snapshot, 1, "IMA_C") == 1
        assert _get_do_state_for_di(snapshot, 2, "IMA_C") == 0

    def test_ima_c_missing_dout(self):
        """IMA_C: DOut pin not found in snapshot."""
        snapshot = {"DIn01": "1"}  # No DOut01

        result = _get_do_state_for_di(snapshot, 1, "IMA_C")
        assert result == 0

    def test_ima_c_invalid_dout_value(self):
        """IMA_C: DOut has invalid value."""
        snapshot = {"DOut01": "invalid"}

        result = _get_do_state_for_di(snapshot, 1, "IMA_C")
        assert result == 0

    def test_ima_c_float_dout_value(self):
        """IMA_C: DOut has float value (should convert to int)."""
        snapshot = {"DOut01": "1.0", "DOut02": "0.0"}

        assert _get_do_state_for_di(snapshot, 1, "IMA_C") == 1
        assert _get_do_state_for_di(snapshot, 2, "IMA_C") == 0

    def test_other_model_returns_zero(self):
        """Other models: Always return 0."""
        snapshot = {"DOut01": "1", "DOut02": "1"}

        assert _get_do_state_for_di(snapshot, 1, "SD400") == 0
        assert _get_do_state_for_di(snapshot, 1, "TECO_VFD") == 0
        assert _get_do_state_for_di(snapshot, 1, "UNKNOWN") == 0

    def test_pin_number_formatting(self):
        """Pin numbers are correctly formatted (01, 02, ..., 99)."""
        snapshot = {
            "DOut01": "1",
            "DOut09": "1",
            "DOut10": "1",
            "DOut99": "1",
        }

        assert _get_do_state_for_di(snapshot, 1, "IMA_C") == 1
        assert _get_do_state_for_di(snapshot, 9, "IMA_C") == 1
        assert _get_do_state_for_di(snapshot, 10, "IMA_C") == 1
        assert _get_do_state_for_di(snapshot, 99, "IMA_C") == 1


class TestConvertDiModuleSnapshot:
    """Test convert_di_module_snapshot() main function."""

    def test_ima_c_with_dout_mapping(self):
        """IMA_C: DOut values correctly mapped to MCStatus0."""
        snapshot = {
            "DIn01": "1",
            "DIn02": "0",
            "DOut01": "1",
            "DOut02": "0",
        }

        result = convert_di_module_snapshot(gateway_id="GW123456789AB", slave_id="5", snapshot=snapshot, model="IMA_C")

        assert len(result) == 2

        # DIn01 record
        assert result[0]["Data"]["Relay0"] == 1  # DIn01 value
        assert result[0]["Data"]["MCStatus0"] == 1  # DOut01 value
        assert result[0]["DeviceID"].endswith("050SR")

        # DIn02 record
        assert result[1]["Data"]["Relay0"] == 0  # DIn02 value
        assert result[1]["Data"]["MCStatus0"] == 0  # DOut02 value
        assert result[1]["DeviceID"].endswith("051SR")

    def test_ima_c_partial_dout(self):
        """IMA_C: Only some DOut pins exist."""
        snapshot = {
            "DIn01": "1",
            "DIn02": "0",
            "DOut01": "1",
            # DOut02 missing
        }

        result = convert_di_module_snapshot(gateway_id="GW123456789AB", slave_id="5", snapshot=snapshot, model="IMA_C")

        assert len(result) == 2
        assert result[0]["Data"]["MCStatus0"] == 1  # DOut01 exists
        assert result[1]["Data"]["MCStatus0"] == 0  # DOut02 missing, default to 0

    def test_ima_c_no_dout(self):
        """IMA_C: No DOut pins in snapshot."""
        snapshot = {
            "DIn01": "1",
            "DIn02": "0",
        }

        result = convert_di_module_snapshot(gateway_id="GW123456789AB", slave_id="5", snapshot=snapshot, model="IMA_C")

        assert len(result) == 2
        assert result[0]["Data"]["MCStatus0"] == 0
        assert result[1]["Data"]["MCStatus0"] == 0

    def test_other_model_no_dout_mapping(self):
        """Other models: MCStatus0 always 0 regardless of DOut."""
        snapshot = {
            "DIn01": "1",
            "DIn02": "0",
            "DOut01": "1",
            "DOut02": "1",
        }

        result = convert_di_module_snapshot(gateway_id="GW123456789AB", slave_id="3", snapshot=snapshot, model="SD400")

        assert len(result) == 2
        assert result[0]["Data"]["Relay0"] == 1  # DIn values correct
        assert result[1]["Data"]["Relay0"] == 0
        assert result[0]["Data"]["MCStatus0"] == 0  # No DOut mapping
        assert result[1]["Data"]["MCStatus0"] == 0

    def test_multiple_di_pins_sorted(self):
        """Multiple DI pins are processed in numeric order."""
        snapshot = {
            "DIn03": "1",
            "DIn01": "1",
            "DIn02": "0",
            "DOut01": "1",
            "DOut02": "0",
            "DOut03": "1",
        }

        result = convert_di_module_snapshot(gateway_id="GW123456789AB", slave_id="5", snapshot=snapshot, model="IMA_C")

        assert len(result) == 3

        # Check order: DIn01, DIn02, DIn03
        assert result[0]["DeviceID"].endswith("050SR")  # idx=0
        assert result[0]["Data"]["MCStatus0"] == 1  # DOut01

        assert result[1]["DeviceID"].endswith("051SR")  # idx=1
        assert result[1]["Data"]["MCStatus0"] == 0  # DOut02

        assert result[2]["DeviceID"].endswith("052SR")  # idx=2
        assert result[2]["Data"]["MCStatus0"] == 1  # DOut03

    def test_no_di_pins(self):
        """No DIn pins in snapshot returns empty list."""
        snapshot = {
            "DOut01": "1",
            "ByPass": "0",
        }

        result = convert_di_module_snapshot(gateway_id="GW123456789AB", slave_id="5", snapshot=snapshot, model="IMA_C")

        assert result == []

    def test_invalid_di_value_skipped(self):
        """Invalid DIn values are skipped with warning."""
        snapshot = {
            "DIn01": "invalid",
            "DIn02": "0",
            "DOut01": "1",
            "DOut02": "0",
        }

        result = convert_di_module_snapshot(gateway_id="GW123456789AB", slave_id="5", snapshot=snapshot, model="IMA_C")

        # Only DIn02 should be processed
        assert len(result) == 1
        assert result[0]["Data"]["Relay0"] == 0
        assert result[0]["Data"]["MCStatus0"] == 0
        assert result[0]["DeviceID"].endswith("051SR")  # Still uses idx=0

    def test_device_id_format(self):
        """DeviceID format is correct."""
        snapshot = {"DIn01": "1", "DOut01": "1"}

        result = convert_di_module_snapshot(gateway_id="GW123456789AB", slave_id="5", snapshot=snapshot, model="IMA_C")

        device_id = result[0]["DeviceID"]
        assert device_id.startswith("GW123456789")  # First 11 chars
        assert "050" in device_id  # slave_id
        assert device_id.endswith("050SR")  # EquipmentType.SR + idx

    def test_data_structure_complete(self):
        """Data dict contains all required fields."""
        snapshot = {"DIn01": "1", "DOut01": "1"}

        result = convert_di_module_snapshot(gateway_id="GW123456789AB", slave_id="5", snapshot=snapshot, model="IMA_C")

        data = result[0]["Data"]
        assert set(data.keys()) == {"Relay0", "Relay1", "MCStatus0", "MCStatus1", "ByPass"}
        assert data["Relay0"] in [0, 1]
        assert data["Relay1"] == 0
        assert data["MCStatus0"] in [0, 1]
        assert data["MCStatus1"] == 0
        assert data["ByPass"] == 0

    def test_high_pin_numbers(self):
        """High pin numbers (DIn10+) are handled correctly."""
        snapshot = {
            "DIn10": "1",
            "DIn99": "0",
            "DOut10": "1",
            "DOut99": "0",
        }

        result = convert_di_module_snapshot(gateway_id="GW123456789AB", slave_id="5", snapshot=snapshot, model="IMA_C")

        assert len(result) == 2
        assert result[0]["Data"]["Relay0"] == 1  # DIn10
        assert result[0]["Data"]["MCStatus0"] == 1  # DOut10
        assert result[1]["Data"]["Relay0"] == 0  # DIn99
        assert result[1]["Data"]["MCStatus0"] == 0  # DOut99


class TestIntegrationWithDeviceIdPolicy:
    """Integration tests with actual DeviceIdPolicy."""

    def test_full_conversion_ima_c(self):
        """Full conversion flow for IMA_C."""
        snapshot = {
            "DIn01": "1",
            "DIn02": "0",
            "DIn03": "1",
            "DIn04": "0",
            "DOut01": "0",
            "DOut02": "1",
            "DOut03": "0",
            "DOut04": "1",
        }

        result = convert_di_module_snapshot(gateway_id="GW98765432100", slave_id="7", snapshot=snapshot, model="IMA_C")

        assert len(result) == 4

        for i, record in enumerate(result):
            assert "DeviceID" in record
            assert "Data" in record
            assert record["DeviceID"].startswith("GW987654321")
            assert "SR" in record["DeviceID"]

            # Verify DIn/DOut mapping
            di_value = int(snapshot[f"DIn{i+1:02d}"])
            do_value = int(snapshot[f"DOut{i+1:02d}"])
            assert record["Data"]["Relay0"] == di_value
            assert record["Data"]["MCStatus0"] == do_value
