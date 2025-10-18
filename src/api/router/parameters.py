"""
Parameter Operation Router

Defines API endpoints for parameter read/write operations.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependency import get_parameter_service
from api.model.requests import ReadMultipleParametersRequest, ReadSingleParameterRequest, WriteParameterRequest
from api.model.responses import (
    ReadMultipleParametersResponse,
    ReadParameterResponse,
    ResponseStatus,
    WriteParameterResponse,
)
from api.service.parameter_service import ParameterService

router = APIRouter()


@router.post(
    "/read",
    response_model=ReadParameterResponse,
    summary="Read a single parameter",
    description="Read a single parameter value from the specified device",
)
async def read_single_parameter(
    request: ReadSingleParameterRequest, service: ParameterService = Depends(get_parameter_service)
) -> ReadParameterResponse:
    """
    Read a single parameter value.

    Args:
        request: The request object containing `device_id` and `parameter`.

    Returns:
        ReadParameterResponse: The response containing the parameter value.
    """
    param_value = await service.read_parameter(device_id=request.device_id, parameter=request.parameter)

    status_enum = ResponseStatus.SUCCESS if param_value.is_valid else ResponseStatus.FAILED

    return ReadParameterResponse(
        status=status_enum,
        device_id=request.device_id,
        parameter=param_value,
        message=param_value.error_message if not param_value.is_valid else None,
    )


@router.post(
    "/read-multiple",
    response_model=ReadMultipleParametersResponse,
    summary="Read multiple parameters",
    description="Read multiple parameter values from the specified device",
)
async def read_multiple_parameters(
    request: ReadMultipleParametersRequest, service: ParameterService = Depends(get_parameter_service)
) -> ReadMultipleParametersResponse:
    """
    Read multiple parameter values.

    Args:
        request: The request object containing `device_id` and a list of `parameters`.

    Returns:
        ReadMultipleParametersResponse: The response containing multiple parameter values.
    """
    param_values = await service.read_multiple_parameters(device_id=request.device_id, parameters=request.parameters)

    success_count = sum(1 for p in param_values if p.is_valid)
    error_count = len(param_values) - success_count

    if error_count == 0:
        status_enum = ResponseStatus.SUCCESS
    elif success_count == 0:
        status_enum = ResponseStatus.FAILED
    else:
        status_enum = ResponseStatus.PARTIAL_SUCCESS

    return ReadMultipleParametersResponse(
        status=status_enum,
        device_id=request.device_id,
        parameters=param_values,
        success_count=success_count,
        error_count=error_count,
    )


@router.post(
    "/write",
    response_model=WriteParameterResponse,
    summary="Write a parameter",
    description="Write a value to a specific parameter of the given device",
)
async def write_parameter(
    request: WriteParameterRequest, service: ParameterService = Depends(get_parameter_service)
) -> WriteParameterResponse:
    """
    Write a parameter value.

    Args:
        request: The request object containing `device_id`, `parameter`, and `value`.

    Returns:
        WriteParameterResponse: The response containing the result of the write operation.
    """
    result = await service.write_parameter(
        device_id=request.device_id, parameter=request.parameter, value=request.value, force=request.force
    )

    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=result.get("error", "Write operation failed")
        )

    return WriteParameterResponse(
        status=ResponseStatus.SUCCESS,
        device_id=request.device_id,
        parameter=request.parameter,
        previous_value=result.get("previous_value"),
        new_value=result["new_value"],
        was_forced=result.get("was_forced", False),
    )
