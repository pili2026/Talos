"""
API Request Data Models

Defines input data structures for all API endpoints,
following Pydantic validation rules.
"""

from typing import Any
from pydantic import BaseModel, Field, field_validator


class ReadSingleParameterRequest(BaseModel):
    """
    Request model for reading a single parameter.

    Attributes:
        device_id: Unique device identifier.
        parameter: Parameter name (e.g., 'hz', 'current').
    """

    device_id: str = Field(..., min_length=1, example="vfd_001")
    parameter: str = Field(..., min_length=1, example="hz")

    @field_validator("parameter")
    def validate_parameter_format(cls, v: str) -> str:
        """Validate parameter name format."""
        if not v.replace("_", "").isalnum():
            raise ValueError("Parameter must be alphanumeric with underscores")
        return v.upper()


class ReadMultipleParametersRequest(BaseModel):
    """
    Request model for reading multiple parameters.

    Attributes:
        device_id: Unique device identifier.
        parameters: List of parameter names.
    """

    device_id: str = Field(..., example="vfd_001")
    parameters: list[str] = Field(..., min_items=1, max_items=50, example=["hz", "current", "voltage"])

    @field_validator("parameters")
    def validate_parameters_unique(cls, v):
        """Ensure parameter list has no duplicates."""
        if len(v) != len(set(v)):
            raise ValueError("Parameters must be unique")
        return [p.upper() for p in v]


class WriteParameterRequest(BaseModel):
    """
    Request model for writing a parameter value.

    Attributes:
        device_id: Unique device identifier.
        parameter: Parameter name.
        value: Value to be written.
        force: Whether to force write (ignore constraint validation).
    """

    device_id: str = Field(..., example="vfd_001")
    parameter: str = Field(..., example="hz")
    value: float = Field(..., example=50.0)
    force: bool = Field(False, description="Force write without constraint validation")


class BatchReadDevicesRequest(BaseModel):
    """Batch read request for multiple devices"""

    device_ids: list[str] = Field(..., min_items=1, max_items=50, example=["LITEON_EVO6800_1", "TECO_VFD_2"])
    parameters: list[str] = Field(..., min_items=1, max_items=20, example=["RW_HZ", "CURRENT"])


class BatchWriteRequest(BaseModel):
    """Batch write request for multiple devices"""

    device_ids: list[str] = Field(..., min_items=1, max_items=50)
    parameter: str = Field(..., example="RW_HZ")
    value: float = Field(..., example=50.0)
    force: bool = Field(False, description="Force write without constraint validation")


class BatchWriteMultipleRequest(BaseModel):
    """Batch write request for multiple devices and multiple parameters"""

    writes: list[dict[str, Any]] = Field(
        ...,
        min_items=1,
        max_items=100,
        example=[
            {"device_id": "LITEON_EVO6800_1", "parameter": "RW_HZ", "value": 50.0},
            {"device_id": "TECO_VFD_2", "parameter": "RW_HZ", "value": 55.0},
        ],
    )
    force: bool = False


class BatchValidateRequest(BaseModel):
    """Batch validation request"""

    device_ids: list[str] = Field(..., min_items=1, max_items=100, example=["LITEON_EVO6800_1", "TECO_VFD_2"])


class BatchReadAllRequest(BaseModel):
    """Batch read-all-parameters request"""

    device_ids: list[str] = Field(..., min_items=1, max_items=50, example=["LITEON_EVO6800_1", "SD400_3"])
