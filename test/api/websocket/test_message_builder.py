"""
Tests for WebSocket MessageBuilder.

Tests focus on message format consistency and required fields.
"""

from api.websocket.message_builder import MessageBuilder


class TestConnectionMessages:
    """Test connection-related messages."""

    def test_when_connection_established_then_contains_required_fields(self):
        """Test connection acknowledgment message structure."""
        msg = MessageBuilder.connection_established(
            device_id="TEST_DEVICE",
            parameters=["param1", "param2"],
            interval=1.5,
            support_control=True,
        )

        assert msg["type"] == "connection_status"
        assert msg["device_id"] == "TEST_DEVICE"
        assert msg["parameters"] == ["param1", "param2"]
        assert msg["interval"] == 1.5
        assert msg["features"]["monitoring"] is True
        assert msg["features"]["control"] is True

    def test_when_multi_device_connection_then_contains_device_ids(self):
        """Test multi-device connection acknowledgment."""
        msg = MessageBuilder.multi_device_connection_established(
            device_ids=["DEV1", "DEV2"], parameters=["temp", "pressure"], interval=2.0
        )

        assert msg["type"] == "connection_status"
        assert msg["device_ids"] == ["DEV1", "DEV2"]
        assert msg["parameters"] == ["temp", "pressure"]
        assert msg["interval"] == 2.0

    def test_when_connection_failed_then_contains_error_details(self):
        """Test connection failure message structure."""
        msg = MessageBuilder.connection_failed(device_id="FAILED_DEV", reason="Device not responding")

        assert msg["type"] == "error"
        assert msg["code"] == "CONNECTION_FAILED"
        assert "device_id" in msg
        assert msg["device_id"] == "FAILED_DEV"
        assert msg["reason"] == "Device not responding"

    def test_when_connection_lost_then_contains_correct_code(self):
        """Test connection lost message."""
        msg = MessageBuilder.connection_lost(device_id="LOST_DEV")

        assert msg["type"] == "error"
        assert msg["code"] == "CONNECTION_LOST"
        assert msg["device_id"] == "LOST_DEV"


class TestErrorMessages:
    """Test error message construction."""

    def test_when_generic_error_then_contains_message(self):
        """Test generic error message."""
        msg = MessageBuilder.error(message="Something went wrong")

        assert msg["type"] == "error"
        assert msg["message"] == "Something went wrong"
        assert "code" not in msg

    def test_when_error_with_code_then_includes_code(self):
        """Test error message with error code."""
        msg = MessageBuilder.error(message="Invalid request", code="INVALID_REQUEST")

        assert msg["type"] == "error"
        assert msg["message"] == "Invalid request"
        assert msg["code"] == "INVALID_REQUEST"

    def test_when_error_with_details_then_includes_details(self):
        """Test error message with additional details."""
        details = {"field": "parameter", "expected": "string"}
        msg = MessageBuilder.error(message="Validation failed", code="VALIDATION_ERROR", details=details)

        assert msg["type"] == "error"
        assert msg["field"] == "parameter"
        assert msg["expected"] == "string"

    def test_when_device_not_found_then_contains_device_id(self):
        """Test device not found error."""
        msg = MessageBuilder.device_not_found(device_id="MISSING_DEV")

        assert msg["type"] == "error"
        assert msg["code"] == "DEVICE_NOT_FOUND"
        assert msg["device_id"] == "MISSING_DEV"

    def test_when_no_parameters_available_then_contains_device_id(self):
        """Test no parameters available error."""
        msg = MessageBuilder.no_parameters_available(device_id="NO_PARAM_DEV")

        assert msg["type"] == "error"
        assert msg["code"] == "NO_PARAMETERS"
        assert msg["device_id"] == "NO_PARAM_DEV"


class TestDataMessages:
    """Test data update message construction."""

    def test_when_data_update_then_contains_timestamp(self):
        """Test data update message includes timestamp."""
        data = {"temp": {"value": 25.5, "unit": "°C"}}
        msg = MessageBuilder.data_update(device_id="TEMP_SENSOR", data=data)

        assert msg["type"] == "data"
        assert msg["device_id"] == "TEMP_SENSOR"
        assert "timestamp" in msg
        assert msg["data"] == data
        assert "errors" not in msg

    def test_when_data_update_with_errors_then_includes_errors(self):
        """Test data update with errors."""
        data = {"temp": {"value": 25.5, "unit": "°C"}}
        errors = ["humidity: Sensor timeout"]
        msg = MessageBuilder.data_update(device_id="SENSOR", data=data, errors=errors)

        assert msg["type"] == "data"
        assert msg["errors"] == errors

    def test_when_multi_device_data_then_contains_devices_dict(self):
        """Test multi-device data update."""
        devices_data = {
            "DEV1": {"temp": {"value": 25.5, "unit": "°C"}},
            "DEV2": {"pressure": {"value": 101.3, "unit": "kPa"}},
        }
        msg = MessageBuilder.multi_device_data_update(devices_data=devices_data)

        assert msg["type"] == "data"
        assert "timestamp" in msg
        assert msg["devices"] == devices_data


class TestControlMessages:
    """Test control command message construction."""

    def test_when_write_success_then_contains_result_fields(self):
        """Test successful write result message."""
        msg = MessageBuilder.write_success(
            device_id="VFD_01",
            parameter="frequency",
            value=50.0,
            previous_value=45.0,
            new_value=50.0,
            was_forced=False,
        )

        assert msg["type"] == "write_result"
        assert msg["device_id"] == "VFD_01"
        assert msg["parameter"] == "frequency"
        assert msg["value"] == 50.0
        assert msg["success"] is True
        assert msg["previous_value"] == 45.0
        assert msg["new_value"] == 50.0
        assert msg["was_forced"] is False
        assert "timestamp" in msg
        assert "message" in msg

    def test_when_write_failure_then_contains_error(self):
        """Test failed write result message."""
        msg = MessageBuilder.write_failure(
            device_id="VFD_01", parameter="frequency", value=50.0, error="Device timeout"
        )

        assert msg["type"] == "write_result"
        assert msg["device_id"] == "VFD_01"
        assert msg["parameter"] == "frequency"
        assert msg["value"] == 50.0
        assert msg["success"] is False
        assert msg["error"] == "Device timeout"
        assert "timestamp" in msg

    def test_when_invalid_write_request_then_contains_request_details(self):
        """Test invalid write request error."""
        request = {"action": "write", "parameter": "freq"}
        msg = MessageBuilder.invalid_write_request(request=request)

        assert msg["type"] == "error"
        assert msg["code"] == "INVALID_WRITE_REQUEST"
        assert msg["request"] == request

    def test_when_pong_then_contains_timestamp(self):
        """Test pong response message."""
        msg = MessageBuilder.pong()

        assert msg["type"] == "pong"
        assert "timestamp" in msg

    def test_when_unknown_action_then_lists_supported_actions(self):
        """Test unknown action error message."""
        msg = MessageBuilder.unknown_action(action="invalid_action")

        assert msg["type"] == "error"
        assert msg["code"] == "UNKNOWN_ACTION"
        assert "supported_actions" in msg
        assert isinstance(msg["supported_actions"], list)


class TestMessageConsistency:
    """Test message format consistency across all message types."""

    def test_when_any_error_then_has_type_error(self):
        """Test all error messages have type 'error'."""
        error_builders = [
            MessageBuilder.error("test"),
            MessageBuilder.connection_failed("dev", "reason"),
            MessageBuilder.connection_lost("dev"),
            MessageBuilder.device_not_found("dev"),
            MessageBuilder.no_parameters_available("dev"),
            MessageBuilder.connection_error("dev", "error"),
            MessageBuilder.service_unavailable(),
            MessageBuilder.no_devices_specified(),
            MessageBuilder.invalid_write_request({}),
            MessageBuilder.unknown_action("test"),
            MessageBuilder.too_many_errors(),
        ]

        for msg in error_builders:
            assert msg["type"] == "error", f"Message {msg} should have type 'error'"

    def test_when_any_data_message_then_has_timestamp(self):
        """Test all data messages include timestamps."""
        data_builders = [
            MessageBuilder.data_update("dev", {}),
            MessageBuilder.multi_device_data_update({}),
            MessageBuilder.write_success("dev", "param", 1),
            MessageBuilder.write_failure("dev", "param", 1, "error"),
            MessageBuilder.pong(),
        ]

        for msg in data_builders:
            assert "timestamp" in msg, f"Message {msg} should have timestamp"
