"""Tests for register combination formulas."""

from util.register_formula import combine_32bit_be, combine_32bit_le, combine_32bit_signed_be, combine_32bit_signed_le


class TestCombine32BitBE:
    """Tests for Big Endian 32-bit combination."""

    def test_when_be_words_valid_then_combines_correctly(self):
        assert combine_32bit_be(0, 12345) == 12345
        assert combine_32bit_be(1, 34463) == 99999

    def test_when_be_words_are_max_then_combined_value_is_uint32_max(self):
        assert combine_32bit_be(0xFFFF, 0xFFFF) == 4294967295

    def test_when_float_inputs_provided_then_casted_and_combined_correctly(self):
        """Test that float inputs are properly converted to int."""
        assert combine_32bit_be(0.0, 12345.0) == 12345
        assert combine_32bit_be(1.0, 34463.0) == 99999

    def test_when_be_inputs_contain_none_then_returns_none(self):
        assert combine_32bit_be(None, 100) is None
        assert combine_32bit_be(100, None) is None
        assert combine_32bit_be(None, None) is None


class TestCombine32BitLE:
    """Tests for Little Endian 32-bit combination."""

    def test_when_le_words_valid_then_combines_correctly(self):
        assert combine_32bit_le(12345, 0) == 12345
        assert combine_32bit_le(34463, 1) == 99999

    def test_when_le_words_are_max_then_combined_value_is_uint32_max(self):
        assert combine_32bit_le(0xFFFF, 0xFFFF) == 4294967295

    def test_when_float_inputs_provided_then_casted_and_combined_correctly(self):
        """Test that float inputs are properly converted to int."""
        assert combine_32bit_le(12345.0, 0.0) == 12345
        assert combine_32bit_le(34463.0, 1.0) == 99999

    def test_when_le_inputs_contain_none_then_returns_none(self):
        assert combine_32bit_le(None, 100) is None
        assert combine_32bit_le(100, None) is None


class TestCombine32BitSignedBE:
    """Tests for Big Endian signed 32-bit combination."""

    def test_when_be_signed_words_form_positive_value_then_returns_expected(self):
        assert combine_32bit_signed_be(0, 12345) == 12345
        assert combine_32bit_signed_be(1, 34463) == 99999

    def test_when_be_signed_words_form_negative_value_then_interprets_two_complement_correctly(self):
        assert combine_32bit_signed_be(0xFFFF, 0xFFFF) == -1
        assert combine_32bit_signed_be(0xFFFF, 0xFFFE) == -2

    def test_when_be_signed_words_at_boundary_then_returns_int32_limits(self):
        assert combine_32bit_signed_be(0x7FFF, 0xFFFF) == 2147483647  # Max positive
        assert combine_32bit_signed_be(0x8000, 0x0000) == -2147483648  # Min negative


class TestCombine32BitSignedLE:
    """Tests for Little Endian signed 32-bit combination."""

    def test_when_le_signed_words_form_positive_value_then_returns_expected(self):
        assert combine_32bit_signed_le(12345, 0) == 12345
        assert combine_32bit_signed_le(34463, 1) == 99999

    def test_when_le_signed_words_form_negative_value_then_interprets_two_complement_correctly(self):
        assert combine_32bit_signed_le(0xFFFF, 0xFFFF) == -1
        assert combine_32bit_signed_le(0xFFFE, 0xFFFF) == -2


class TestRealWorldScenarios:
    """Tests using real device data."""

    def test_when_using_gta_a26a_panel_data_then_combines_into_expected_real_world_values(self):
        """Test with actual GTA_A26A panel meter data."""
        # From log: MAXD_HI: 1, MAXD_LO: 11238 → MAXD: 76774
        assert combine_32bit_be(1, 11238) == 76774

        # DEMAND and RATE are 0
        assert combine_32bit_be(0, 0) == 0
