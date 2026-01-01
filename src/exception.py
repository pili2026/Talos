"""Industrial Control System Exception Definitions"""


class TalosError(Exception):
    """Base exception for the Talos system"""

    pass


class DeviceError(TalosError):
    """Base class for device-related exceptions"""

    def __init__(self, message: str, device_id: str | None = None):
        super().__init__(message)
        self.device_id = device_id


class DeviceNotFoundError(DeviceError):
    """Device not found"""

    pass


class DeviceConnectionError(DeviceError):
    """Device connection failure (including Modbus communication errors)"""

    pass


class DeviceTimeoutError(DeviceError):
    """Device response timeout"""

    pass


class DeviceConfigError(DeviceError):
    """Device configuration error"""

    pass


class ParameterError(TalosError):
    """Parameter-related exception"""

    pass


class ParameterNotFoundError(ParameterError):
    """Parameter not found"""

    pass


class ParameterValueError(ParameterError):
    """Parameter value out of allowed range"""

    def __init__(self, message: str, value=None, constraint=None):
        super().__init__(message)
        self.value = value
        self.constraint = constraint
