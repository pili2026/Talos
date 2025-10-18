"""
API Response Data Models

Defines output data structures for all API endpoints,
providing a unified response format.
"""

from pydantic import BaseModel, Field
from datetime import datetime

from api.model.enums import ParameterType, ResponseStatus


class BaseResponse(BaseModel):
    """
    Base response model.

    The base class for all API responses,
    providing a unified response structure.
    """

    status: ResponseStatus = Field(..., description="Response status")
    timestamp: datetime = Field(default_factory=datetime.now, description="Response timestamp")
    message: str | None = Field(None, description="Additional message")


class ParameterValue(BaseModel):
    """
    Parameter value data model.

    Attributes:
        name: Parameter name.
        value: Parameter value.
        unit: Measurement unit.
        type: Parameter type.
    """

    name: str
    value: float
    unit: str | None = None
    type: ParameterType
    is_valid: bool = True
    error_message: str | None = None


class ReadParameterResponse(BaseResponse):
    """
    Response model for reading a single parameter.

    Attributes:
        device_id: Device identifier.
        parameter: Parameter information.
    """

    device_id: str
    parameter: ParameterValue


class ReadMultipleParametersResponse(BaseResponse):
    """
    Response model for reading multiple parameters.

    Attributes:
        device_id: Device identifier.
        parameters: List of parameter information.
        success_count: Number of successfully read parameters.
        error_count: Number of failed parameter reads.
    """

    device_id: str
    parameters: list[ParameterValue]
    success_count: int
    error_count: int


class WriteParameterResponse(BaseResponse):
    """
    Response model for writing a parameter value.

    Attributes:
        device_id: Device identifier.
        parameter: Parameter name.
        previous_value: Value before write.
        new_value: Value after write.
        was_forced: Indicates whether the write was forced.
    """

    device_id: str
    parameter: str
    previous_value: float | None = None
    new_value: float
    was_forced: bool = False


class DeviceInfo(BaseModel):
    """
    Device information model.

    Attributes:
        device_id: Device identifier.
        model: Device model name.
        slave_id: Modbus Slave ID.
        connection_status: Connection status.
        available_parameters: List of available parameters.
    """

    device_id: str
    model: str
    slave_id: str
    connection_status: str  # "online", "offline", "unknown"
    available_parameters: list[str]
    last_seen: datetime | None = None


class DeviceListResponse(BaseResponse):
    """
    Response model for device list.

    Attributes:
        devices: List of device information.
        total_count: Total number of devices.
    """

    devices: list[DeviceInfo]
    total_count: int
