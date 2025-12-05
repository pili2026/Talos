"""Tests for ComputedFieldProcessor."""

from core.device.generic.computed_field_processor import ComputedFieldProcessor


class TestComputedFieldProcessor:
    """Tests for computed field processing."""

    def test_when_no_computed_fields_defined_then_returns_raw_data(self):
        """Test with no computed fields defined."""
        # Arrange
        register_map = {
            "VAL1": {"offset": 0, "format": "u16", "readable": True},
            "VAL2": {"offset": 1, "format": "u16", "readable": True},
        }

        # Act
        processor = ComputedFieldProcessor(register_map)

        # Assert
        assert not processor.has_computed_fields()

        raw_data = {"VAL1": 100, "VAL2": 200}
        result = processor.compute(raw_data)
        assert result == raw_data

    def test_when_single_computed_field_combined_then_returns_expected_value(self):
        """Test with a single computed field."""

        # Arrange
        register_map = {
            "HI": {"offset": 0, "format": "u16", "readable": True},
            "LO": {"offset": 1, "format": "u16", "readable": True},
            "COMBINED": {
                "type": "computed",
                "formula": "combine_32bit_be",
                "inputs": ["HI", "LO"],
                "output_format": "u32",
            },
        }

        # Act
        processor = ComputedFieldProcessor(register_map)

        # Assert
        assert processor.has_computed_fields()

        raw_data = {"HI": 1, "LO": 11238}
        result = processor.compute(raw_data)

        assert result["HI"] == 1
        assert result["LO"] == 11238
        assert result["COMBINED"] == 76774

    def test_when_multiple_computed_fields_defined_then_all_values_computed_correctly(self):
        """Test with multiple computed fields."""
        # Arrange
        register_map = {
            "MAXD_HI": {"offset": 62, "format": "u16", "readable": True},
            "MAXD_LO": {"offset": 63, "format": "u16", "readable": True},
            "DEMAND_HI": {"offset": 64, "format": "u16", "readable": True},
            "DEMAND_LO": {"offset": 65, "format": "u16", "readable": True},
            "MAXD": {
                "type": "computed",
                "formula": "combine_32bit_be",
                "inputs": ["MAXD_HI", "MAXD_LO"],
            },
            "DEMAND": {
                "type": "computed",
                "formula": "combine_32bit_be",
                "inputs": ["DEMAND_HI", "DEMAND_LO"],
            },
        }

        # Act
        processor = ComputedFieldProcessor(register_map)

        raw_data = {
            "MAXD_HI": 1,
            "MAXD_LO": 11238,
            "DEMAND_HI": 0,
            "DEMAND_LO": 0,
        }

        result = processor.compute(raw_data)

        # Assert
        assert result["MAXD"] == 76774
        assert result["DEMAND"] == 0

    def test_when_computed_field_missing_inputs_then_returns_none(self):
        """Test with missing input data."""
        # Arrange
        register_map = {
            "HI": {"offset": 0, "format": "u16", "readable": True},
            "LO": {"offset": 1, "format": "u16", "readable": True},
            "COMBINED": {
                "type": "computed",
                "formula": "combine_32bit_be",
                "inputs": ["HI", "LO"],
            },
        }

        # Act
        processor = ComputedFieldProcessor(register_map)

        # Missing LO value
        raw_data = {"HI": 1}
        result = processor.compute(raw_data)

        # Assert
        assert result["COMBINED"] is None
