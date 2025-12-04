"""
WebSocket message builder for standardized message formatting.
Centralizes all WebSocket message construction to ensure consistency.
"""

from datetime import datetime
from typing import Any


class MessageBuilder:
    """
    Centralized builder for all WebSocket message formats.

    Ensures consistent message structure across all WebSocket endpoints.
    """

    # ===== Connection Messages =====

    @staticmethod
    def connection_established(
        device_id: str,
        parameters: list[str],
        interval: float,
        support_control: bool = True,
    ) -> dict:
        """
        Build connection acknowledgment message.

        Args:
            device_id: Device identifier
            parameters: List of monitored parameters
            interval: Update interval in seconds
            support_control: Whether control commands are supported

        Returns:
            Connection established message
        """
        return {
            "type": "connected",
            "device_id": device_id,
            "parameters": parameters,
            "interval": interval,
            "features": {
                "monitoring": True,
                "control": support_control,
            },
        }

    @staticmethod
    def multi_device_connection_established(
        device_ids: list[str],
        parameters: list[str] | None,
        interval: float,
    ) -> dict:
        """
        Build multi-device connection acknowledgment message.

        Args:
            device_ids: List of device identifiers
            parameters: List of monitored parameters (optional)
            interval: Update interval in seconds

        Returns:
            Multi-device connection established message
        """
        return {
            "type": "connected",
            "device_ids": device_ids,
            "parameters": parameters,
            "interval": interval,
        }

    # ===== Error Messages =====

    @staticmethod
    def error(
        message: str,
        code: str | None = None,
        details: dict | None = None,
    ) -> dict:
        """
        Build generic error message.

        Args:
            message: Human-readable error message
            code: Machine-readable error code (optional)
            details: Additional error details (optional)

        Returns:
            Error message
        """
        error_msg = {
            "type": "error",
            "message": message,
        }

        if code:
            error_msg["code"] = code

        if details:
            error_msg.update(details)

        return error_msg

    @staticmethod
    def connection_failed(device_id: str, reason: str) -> dict:
        """Build connection test failure message."""
        return MessageBuilder.error(
            message="Failed to connect to device. Please check the connection.",
            code="CONNECTION_FAILED",
            details={"device_id": device_id, "reason": reason},
        )

    @staticmethod
    def connection_lost(device_id: str) -> dict:
        """Build connection lost message."""
        return MessageBuilder.error(
            message="Device connection lost. Please reconnect.",
            code="CONNECTION_LOST",
            details={"device_id": device_id},
        )

    @staticmethod
    def too_many_errors() -> dict:
        """Build too many consecutive errors message."""
        return MessageBuilder.error(
            message="Too many consecutive errors. Closing connection.",
            code="TOO_MANY_ERRORS",
        )

    @staticmethod
    def device_not_found(device_id: str) -> dict:
        """Build device not found error message."""
        return MessageBuilder.error(
            message=f"Device '{device_id}' not found",
            code="DEVICE_NOT_FOUND",
            details={"device_id": device_id},
        )

    @staticmethod
    def no_parameters_available(device_id: str) -> dict:
        """Build no parameters available error message."""
        return MessageBuilder.error(
            message=f"No parameters available for device {device_id}",
            code="NO_PARAMETERS",
            details={"device_id": device_id},
        )

    @staticmethod
    def connection_error(device_id: str, error: str) -> dict:
        """Build connection error message."""
        return MessageBuilder.error(
            message=f"Failed to connect to device: {error}",
            code="CONNECTION_ERROR",
            details={"device_id": device_id, "error": error},
        )

    @staticmethod
    def service_unavailable() -> dict:
        """Build service unavailable error message."""
        return MessageBuilder.error(
            message="AsyncDeviceManager is not available",
            code="SERVICE_UNAVAILABLE",
        )

    @staticmethod
    def no_devices_specified() -> dict:
        """Build no devices specified error message."""
        return MessageBuilder.error(
            message="No devices specified",
            code="INVALID_REQUEST",
        )

    # ===== Data Messages =====

    @staticmethod
    def data_update(
        device_id: str,
        data: dict[str, dict[str, Any]],
        errors: list[str] | None = None,
    ) -> dict:
        """
        Build data update message for single device.

        Args:
            device_id: Device identifier
            data: Parameter data dict with structure:
                  {param_name: {"value": val, "unit": unit}}
            errors: List of error messages (optional)

        Returns:
            Data update message
        """
        message = {
            "type": "data",
            "device_id": device_id,
            "timestamp": datetime.now().isoformat(),
            "data": data,
        }

        if errors:
            message["errors"] = errors

        return message

    @staticmethod
    def multi_device_data_update(
        devices_data: dict[str, dict[str, dict[str, Any]]],
    ) -> dict:
        """
        Build data update message for multiple devices.

        Args:
            devices_data: Nested dict with structure:
                         {device_id: {param_name: {"value": val, "unit": unit}}}

        Returns:
            Multi-device data update message
        """
        return {
            "type": "data",
            "timestamp": datetime.now().isoformat(),
            "devices": devices_data,
        }

    # ===== Control Messages =====

    @staticmethod
    def write_success(
        device_id: str,
        parameter: str,
        value: Any,
        previous_value: Any | None = None,
        new_value: Any | None = None,
        was_forced: bool = False,
    ) -> dict:
        """
        Build successful write result message.

        Args:
            device_id: Device identifier
            parameter: Parameter name
            value: Written value
            previous_value: Previous parameter value (optional)
            new_value: New parameter value after write (optional)
            was_forced: Whether force flag was used

        Returns:
            Write success message
        """
        return {
            "type": "write_result",
            "device_id": device_id,
            "parameter": parameter,
            "value": value,
            "success": True,
            "previous_value": previous_value,
            "new_value": new_value,
            "was_forced": was_forced,
            "message": f"Successfully written {value} to {parameter}",
            "timestamp": datetime.now().isoformat(),
        }

    @staticmethod
    def write_failure(
        device_id: str,
        parameter: str,
        value: Any,
        error: str,
    ) -> dict:
        """
        Build failed write result message.

        Args:
            device_id: Device identifier
            parameter: Parameter name
            value: Attempted value
            error: Error description

        Returns:
            Write failure message
        """
        return {
            "type": "write_result",
            "device_id": device_id,
            "parameter": parameter,
            "value": value,
            "success": False,
            "error": error,
            "timestamp": datetime.now().isoformat(),
        }

    @staticmethod
    def invalid_write_request(request: dict) -> dict:
        """Build invalid write request error message."""
        return MessageBuilder.error(
            message="Missing 'parameter' or 'value'",
            code="INVALID_WRITE_REQUEST",
            details={"request": request},
        )

    # ===== Control Command Messages =====

    @staticmethod
    def pong() -> dict:
        """Build pong response message."""
        return {
            "type": "pong",
            "timestamp": datetime.now().isoformat(),
        }

    @staticmethod
    def unknown_action(action: str) -> dict:
        """Build unknown action error message."""
        return MessageBuilder.error(
            message=f"Unknown action: {action}",
            code="UNKNOWN_ACTION",
            details={"supported_actions": ["write", "ping"]},
        )
