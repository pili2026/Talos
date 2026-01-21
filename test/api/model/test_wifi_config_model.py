import pytest
from fastapi import HTTPException
from api.util.wifi_util import WiFiUtil


class TestValidateConnectRequest:
    """Tests for connection request validation"""

    def test_when_valid_wpa2_request_then_no_exception(self, valid_wpa2_request):
        """Test: no exception is raised for a valid WPA2 request"""
        WiFiUtil.validate_connect_request(valid_wpa2_request)  # Should not raise

    def test_when_valid_open_request_then_no_exception(self, valid_open_request):
        """Test: no exception is raised for a valid open-network request"""
        WiFiUtil.validate_connect_request(valid_open_request)  # Should not raise

    def test_when_open_network_with_psk_then_http_exception(self, invalid_open_with_psk_request):
        """Test: raises HTTPException when an open network includes a PSK"""
        with pytest.raises(HTTPException) as exc_info:
            WiFiUtil.validate_connect_request(invalid_open_with_psk_request)

        assert exc_info.value.status_code == 400
        assert "must not include psk" in exc_info.value.detail

    def test_when_wpa2_without_psk_then_http_exception(self, invalid_wpa2_no_psk_request):
        """Test: raises HTTPException when WPA2 network is missing a PSK"""
        with pytest.raises(HTTPException) as exc_info:
            WiFiUtil.validate_connect_request(invalid_wpa2_no_psk_request)

        assert exc_info.value.status_code == 400
        assert "requires psk" in exc_info.value.detail


class TestMaskSensitiveArgs:
    """Tests for password masking"""

    def test_when_contains_psk_then_masks_value(self):
        """Test: masks the value when PSK is present"""
        cmd = ["wpa_cli", "-i", "wlan0", "set_network", "0", "psk", '"MyPassword123"']

        safe_cmd = WiFiUtil.mask_sensitive_args(cmd)

        assert safe_cmd[-1] == '"***"'
        assert "MyPassword123" not in safe_cmd
        assert safe_cmd[:-1] == cmd[:-1]  # Other parts remain unchanged

    def test_when_no_psk_then_unchanged(self):
        """Test: command remains unchanged when no PSK is present"""
        cmd = ["wpa_cli", "-i", "wlan0", "status"]

        safe_cmd = WiFiUtil.mask_sensitive_args(cmd)

        assert safe_cmd == cmd

    def test_when_multiple_psk_then_masks_all(self):
        """Test: masks all PSK values when multiple PSKs are present"""
        cmd = ["cmd", "psk", '"pass1"', "psk", '"pass2"']

        safe_cmd = WiFiUtil.mask_sensitive_args(cmd)

        assert safe_cmd[2] == '"***"'
        assert safe_cmd[4] == '"***"'


class TestToInt:
    """Tests for string-to-integer conversion"""

    @pytest.mark.parametrize(
        "input_val,expected",
        [
            ("123", 123),
            ("-456", -456),
            ("0", 0),
            ("+789", 789),
        ],
    )
    def test_when_valid_int_string_then_converts(self, input_val, expected):
        """Test: converts valid integer strings"""
        assert WiFiUtil.to_int(input_val) == expected

    @pytest.mark.parametrize(
        "input_val",
        [
            "abc",
            "12.34",
            "",
            "  ",
            "123abc",
            None,
        ],
    )
    def test_when_invalid_string_then_returns_none(self, input_val):
        """Test: returns None for invalid strings"""
        assert WiFiUtil.to_int(input_val) is None


class TestPickSitePriorityDecrement:
    """Tests for site priority selection (DECREMENT mode)"""

    def test_when_all_available_then_returns_4(self):
        """Test: returns 4 when all priorities are available"""
        assert WiFiUtil.pick_site_priority_decrement(set()) == 4

    def test_when_4_used_then_returns_3(self):
        """Test: returns 3 when priority 4 is already used"""
        assert WiFiUtil.pick_site_priority_decrement({4}) == 3

    def test_when_4_and_3_used_then_returns_2(self):
        """Test: returns 2 when priorities 4 and 3 are already used"""
        assert WiFiUtil.pick_site_priority_decrement({4, 3}) == 2

    def test_when_all_used_then_returns_0(self):
        """Test: returns 0 when all priorities are used"""
        assert WiFiUtil.pick_site_priority_decrement({4, 3, 2, 1, 0}) == 0

    def test_when_non_sequential_used_then_returns_highest_available(self):
        """Test: returns the highest available value when used priorities are non-sequential"""
        assert WiFiUtil.pick_site_priority_decrement({4, 2, 0}) == 3


class TestHasAnySsid:
    """Tests for SSID existence checks"""

    def test_when_ssid_exists_then_returns_true(self, sample_wpa_network_rows):
        """Test: returns True when the SSID exists"""
        assert WiFiUtil.has_any_ssid(sample_wpa_network_rows, {"MyNetwork"}) is True

    def test_when_multiple_ssids_one_exists_then_returns_true(self, sample_wpa_network_rows):
        """Test: returns True when at least one SSID exists among multiple candidates"""
        assert WiFiUtil.has_any_ssid(sample_wpa_network_rows, {"NonExistent", "test_rescue"}) is True

    def test_when_no_ssid_exists_then_returns_false(self, sample_wpa_network_rows):
        """Test: returns False when no SSID exists"""
        assert WiFiUtil.has_any_ssid(sample_wpa_network_rows, {"NotFound"}) is False

    def test_when_empty_list_then_returns_false(self):
        """Test: returns False for an empty network list"""
        assert WiFiUtil.has_any_ssid([], {"AnySSID"}) is False


class TestSanitizeSsid:
    """Tests for SSID sanitization and validation"""

    def test_when_valid_ssid_then_returns_as_is(self):
        """Test: returns the SSID as-is when it is valid"""
        display, is_valid, reason = WiFiUtil._sanitize_ssid("MyNetwork-5G")

        assert display == "MyNetwork-5G"
        assert is_valid is True
        assert reason is None

    def test_when_empty_then_returns_hidden(self):
        """Test: returns Hidden for an empty SSID"""
        display, is_valid, reason = WiFiUtil._sanitize_ssid("")

        assert display == "(Hidden SSID)"
        assert is_valid is True

    def test_when_null_byte_then_invalid(self):
        """Test: marks SSID as invalid when it contains a null byte"""
        display, is_valid, reason = WiFiUtil._sanitize_ssid("Network\\x00Name")

        assert display == "(Invalid SSID)"
        assert is_valid is False
        assert "null-byte" in reason

    def test_when_too_long_then_invalid(self):
        """Test: marks SSID as invalid when it exceeds 32 characters"""
        long_ssid = "x" * 33
        display, is_valid, reason = WiFiUtil._sanitize_ssid(long_ssid)

        assert display == "(Invalid SSID)"
        assert is_valid is False
        assert "length" in reason.lower()

    def test_when_only_punctuation_then_valid_with_warning(self):
        """Test: SSID with only punctuation is valid but returns a warning"""
        display, is_valid, reason = WiFiUtil._sanitize_ssid("!!!")

        assert display == "!!!"
        assert is_valid is True
        assert "punctuation" in reason.lower()


class TestDbmToPercent:
    """Tests for dBm-to-percentage conversion"""

    @pytest.mark.parametrize(
        "dbm,expected",
        [
            (-20, 100),
            (-30, 100),
            (-60, 50),
            (-75, 25),
            (-90, 0),
            (-100, 0),
        ],
    )
    def test_dbm_conversion(self, dbm, expected):
        """Test: converts dBm values to percentages"""
        assert WiFiUtil._dbm_to_percent(dbm) == expected
