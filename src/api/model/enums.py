"""
API Enum Definitions

Centralized management of all enumeration values
to ensure type safety.
"""

from enum import StrEnum


class ResponseStatus(StrEnum):
    """API response status"""

    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    ERROR = "error"


class ParameterType(StrEnum):
    """Parameter type"""

    ANALOG_INPUT = "analog_input"
    ANALOG_OUTPUT = "analog_output"
    DIGITAL_INPUT = "digital_input"
    DIGITAL_OUTPUT = "digital_output"
    READ_WRITE = "read_write"
    READ_ONLY = "read_only"


class DeviceConnectionStatus(StrEnum):
    """Device connection status"""

    ONLINE = "online"
    OFFLINE = "offline"
    UNKNOWN = "unknown"
    CONNECTING = "connecting"
    ERROR = "error"


class OperationType(StrEnum):
    """Operation type"""

    READ = "read"
    WRITE = "write"
    VALIDATE = "validate"
    MONITOR = "monitor"
