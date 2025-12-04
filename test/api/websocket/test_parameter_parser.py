"""
Tests for parameter parsing utilities.

Tests parameter list parsing following Talos patterns.
"""

import pytest

from api.websocket.parameter_paser import (
    ParameterListBuilder,
    ParameterParseError,
    parse_device_list,
    parse_multi_device_parameters,
    parse_parameter_list,
    validate_parameter_names,
)


class MockConfigRepository:
    """Mock configuration repository for testing."""

    def __init__(self, devices: dict[str, dict] | None = None):
        self.devices = devices or {}

    def get_device_config(self, device_id: str) -> dict | None:
        """Get device configuration."""
        return self.devices.get(device_id)


class TestParseParameterList:
    """Test parse_parameter_list function."""

    def test_when_parameters_specified_then_returns_parsed_list(self):
        """Test parsing specified parameters."""
        config_repo = MockConfigRepository()

        params = parse_parameter_list("temp,pressure,humidity", "DEVICE_01", config_repo)

        assert params == ["temp", "pressure", "humidity"]

    def test_when_parameters_with_spaces_then_strips_whitespace(self):
        """Test whitespace handling."""
        config_repo = MockConfigRepository()

        params = parse_parameter_list(" temp , pressure , humidity ", "DEVICE_01", config_repo)

        assert params == ["temp", "pressure", "humidity"]

    def test_when_no_parameters_then_uses_device_config(self):
        """Test fallback to device configuration."""
        config_repo = MockConfigRepository({"DEVICE_01": {"available_parameters": ["temp", "pressure"]}})

        params = parse_parameter_list(None, "DEVICE_01", config_repo)

        assert params == ["temp", "pressure"]

    def test_when_device_not_found_then_raises_error(self):
        """Test error when device not found."""
        config_repo = MockConfigRepository()

        with pytest.raises(ParameterParseError) as exc_info:
            parse_parameter_list(None, "UNKNOWN_DEVICE", config_repo)

        assert "not found" in str(exc_info.value)
        assert exc_info.value.device_id == "UNKNOWN_DEVICE"

    def test_when_no_available_parameters_then_raises_error(self):
        """Test error when device has no parameters."""
        config_repo = MockConfigRepository({"DEVICE_01": {"available_parameters": []}})

        with pytest.raises(ParameterParseError) as exc_info:
            parse_parameter_list(None, "DEVICE_01", config_repo)

        assert "No parameters available" in str(exc_info.value)


class TestParseDeviceList:
    """Test parse_device_list function."""

    def test_when_valid_device_list_then_returns_parsed(self):
        """Test parsing valid device list."""
        devices = parse_device_list("VFD_01,VFD_02,VFD_03")

        assert devices == ["VFD_01", "VFD_02", "VFD_03"]

    def test_when_device_list_with_spaces_then_strips(self):
        """Test whitespace handling."""
        devices = parse_device_list(" VFD_01 , VFD_02 , VFD_03 ")

        assert devices == ["VFD_01", "VFD_02", "VFD_03"]

    def test_when_empty_string_then_raises_error(self):
        """Test error on empty string."""
        with pytest.raises(ParameterParseError) as exc_info:
            parse_device_list("")

        assert "No devices specified" in str(exc_info.value)

    def test_when_only_commas_then_raises_error(self):
        """Test error on string with only commas."""
        with pytest.raises(ParameterParseError):
            parse_device_list(",,,")


class TestValidateParameterNames:
    """Test validate_parameter_names function."""

    def test_when_all_valid_then_returns_all_valid(self):
        """Test all parameters valid."""
        valid, invalid = validate_parameter_names(["temp", "pressure"], ["temp", "pressure", "humidity"], "DEVICE_01")

        assert valid == ["temp", "pressure"]
        assert invalid == []

    def test_when_some_invalid_then_separates_valid_invalid(self):
        """Test mixed valid and invalid parameters."""
        valid, invalid = validate_parameter_names(
            ["temp", "invalid", "pressure"],
            ["temp", "pressure", "humidity"],
            "DEVICE_01",
        )

        assert valid == ["temp", "pressure"]
        assert invalid == ["invalid"]

    def test_when_all_invalid_then_returns_empty_valid(self):
        """Test all parameters invalid."""
        valid, invalid = validate_parameter_names(["invalid1", "invalid2"], ["temp", "pressure"], "DEVICE_01")

        assert valid == []
        assert invalid == ["invalid1", "invalid2"]

    def test_when_empty_list_then_returns_empty(self):
        """Test empty parameter list."""
        valid, invalid = validate_parameter_names([], ["temp", "pressure"], "DEVICE_01")

        assert valid == []
        assert invalid == []


class TestParameterListBuilder:
    """Test ParameterListBuilder class."""

    def test_when_build_with_query_string_then_returns_parsed(self):
        """Test building with query string."""
        config_repo = MockConfigRepository()
        builder = ParameterListBuilder(config_repo)

        params = builder.for_device("DEVICE_01").from_query_string("temp,pressure").build()

        assert params == ["temp", "pressure"]

    def test_when_build_without_query_string_then_uses_config(self):
        """Test building from device configuration."""
        config_repo = MockConfigRepository({"DEVICE_01": {"available_parameters": ["temp", "pressure", "humidity"]}})
        builder = ParameterListBuilder(config_repo)

        params = builder.for_device("DEVICE_01").from_query_string(None).build()

        assert params == ["temp", "pressure", "humidity"]

    def test_when_build_without_device_then_raises_error(self):
        """Test error when device not set."""
        config_repo = MockConfigRepository()
        builder = ParameterListBuilder(config_repo)

        with pytest.raises(ValueError, match="Device ID must be set"):
            builder.from_query_string("temp").build()

    def test_when_validate_enabled_then_filters_invalid(self):
        """Test validation filtering."""
        config_repo = MockConfigRepository({"DEVICE_01": {"available_parameters": ["temp", "pressure"]}})
        builder = ParameterListBuilder(config_repo)

        params = builder.for_device("DEVICE_01").from_query_string("temp,invalid,pressure").validate().build()

        assert params == ["temp", "pressure"]

    def test_when_fluent_interface_then_returns_builder(self):
        """Test fluent interface returns builder."""
        config_repo = MockConfigRepository()
        builder = ParameterListBuilder(config_repo)

        result = builder.for_device("DEVICE_01")
        assert isinstance(result, ParameterListBuilder)

        result = result.from_query_string("temp")
        assert isinstance(result, ParameterListBuilder)

        result = result.validate()
        assert isinstance(result, ParameterListBuilder)


class TestParseMultiDeviceParameters:
    """Test parse_multi_device_parameters function."""

    def test_when_parameters_specified_then_same_for_all(self):
        """Test specified parameters used for all devices."""
        config_repo = MockConfigRepository()

        params = parse_multi_device_parameters(["VFD_01", "VFD_02"], "frequency,current", config_repo)

        assert params == {
            "VFD_01": ["frequency", "current"],
            "VFD_02": ["frequency", "current"],
        }

    def test_when_no_parameters_then_each_device_config(self):
        """Test each device uses its own parameters."""
        config_repo = MockConfigRepository(
            {
                "VFD_01": {"available_parameters": ["frequency", "current"]},
                "VFD_02": {"available_parameters": ["frequency", "voltage"]},
            }
        )

        params = parse_multi_device_parameters(["VFD_01", "VFD_02"], None, config_repo)

        assert params == {
            "VFD_01": ["frequency", "current"],
            "VFD_02": ["frequency", "voltage"],
        }

    def test_when_device_not_found_then_empty_list(self):
        """Test missing device gets empty list."""
        config_repo = MockConfigRepository({"VFD_01": {"available_parameters": ["frequency"]}})

        params = parse_multi_device_parameters(["VFD_01", "UNKNOWN"], None, config_repo)

        assert params == {"VFD_01": ["frequency"], "UNKNOWN": []}


class TestParameterParseError:
    """Test ParameterParseError exception."""

    def test_when_created_with_device_id_then_stores(self):
        """Test device_id is stored."""
        error = ParameterParseError("Test error", device_id="DEVICE_01")

        assert error.device_id == "DEVICE_01"
        assert str(error) == "Test error"

    def test_when_created_without_device_id_then_none(self):
        """Test device_id defaults to None."""
        error = ParameterParseError("Test error")

        assert error.device_id is None
