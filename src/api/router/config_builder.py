"""
Config Builder Router

Endpoints for building and validating Talos configuration files.

All endpoints are prefixed with /api/config-builder (registered in app.py).

Endpoints:
  GET  /devices                         – List devices from modbus_device.yml
  GET  /devices/{model}/pins            – Readable/writable pins for a model
  POST /config/control/validate         – Validate control_condition YAML
  POST /config/alert/validate           – Validate alert_condition YAML
  POST /config/control/generate         – Generate control_condition YAML from form data
  POST /config/alert/generate           – Generate alert_condition YAML from form data
  POST /diagram/generate                – Generate Mermaid flowchart from config YAML
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependency import get_yaml_manager
from api.model.config_builder import (
    AlertGenerateRequest,
    ConfigBuilderDeviceInfo,
    ConfigBuilderDeviceListResponse,
    ControlGenerateRequest,
    DevicePinsResponse,
    DiagramRequest,
    DiagramResponse,
    FieldValidationError,
    GenerateResponse,
    PinInfo,
    ValidateRequest,
    ValidationResponse,
)
from api.service.config_builder_service import ConfigBuilderService
from core.util.yaml_manager import YAMLManager

router = APIRouter()
logger = logging.getLogger("ConfigBuilderRouter")


# ============================================================================
# Dependency
# ============================================================================


def get_config_builder_service(
    yaml_manager: YAMLManager = Depends(get_yaml_manager),
) -> ConfigBuilderService:
    """Construct ConfigBuilderService from the shared YAMLManager config directory."""
    return ConfigBuilderService(yaml_manager.config_dir)


# ============================================================================
# Device Endpoints
# ============================================================================


@router.get(
    "/devices",
    response_model=ConfigBuilderDeviceListResponse,
    summary="List devices from config YAML",
    description=(
        "Read modbus_device.yml and return all configured devices with their pin names. "
        "Unlike /api/devices (runtime), this endpoint reads directly from the YAML file."
    ),
)
async def list_config_devices(
    service: ConfigBuilderService = Depends(get_config_builder_service),
) -> ConfigBuilderDeviceListResponse:
    try:
        raw_devices = service.get_devices()
        devices = [ConfigBuilderDeviceInfo(**d) for d in raw_devices]
        return ConfigBuilderDeviceListResponse(devices=devices, total=len(devices))
    except FileNotFoundError as exc:
        logger.error(f"[ConfigBuilder] modbus_device.yml not found: {exc}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="modbus_device.yml not found",
        )
    except Exception as exc:
        logger.error(f"[ConfigBuilder] Failed to list devices: {exc}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to load device config")


@router.get(
    "/devices/{model}/pins",
    response_model=DevicePinsResponse,
    summary="Get readable/writable pins for a device model",
    description=(
        "Load the driver YAML for the given model and return all pin definitions "
        "split into readable and writable lists."
    ),
)
async def get_model_pins(
    model: str,
    service: ConfigBuilderService = Depends(get_config_builder_service),
) -> DevicePinsResponse:
    try:
        result = service.get_device_pins(model)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Model '{model}' not found in modbus_device.yml or driver file missing",
            )
        return DevicePinsResponse(
            model=result["model"],
            readable_pins=[PinInfo(**p) for p in result["readable_pins"]],
            writable_pins=[PinInfo(**p) for p in result["writable_pins"]],
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[ConfigBuilder] Failed to get pins for model '{model}': {exc}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to load driver config")


# ============================================================================
# Validation Endpoints
# ============================================================================


@router.post(
    "/config/control/validate",
    response_model=ValidationResponse,
    summary="Validate control_condition YAML",
    description=(
        "Parse and validate a control_condition YAML string using the existing "
        "ControlConfig Pydantic schema. Returns field-level errors with location paths."
    ),
)
async def validate_control_config(
    request: ValidateRequest,
    service: ConfigBuilderService = Depends(get_config_builder_service),
) -> ValidationResponse:
    try:
        result = service.validate_control_config(request.yaml_content)
        return ValidationResponse(
            valid=result["valid"],
            errors=[FieldValidationError(**e) for e in result["errors"]],
        )
    except Exception as exc:
        logger.error(f"[ConfigBuilder] validate_control_config error: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error during validation",
        )


@router.post(
    "/config/alert/validate",
    response_model=ValidationResponse,
    summary="Validate alert_condition YAML",
    description=(
        "Parse and validate an alert_condition YAML string using the existing "
        "AlertConfig Pydantic schema. Returns field-level errors with location paths."
    ),
)
async def validate_alert_config(
    request: ValidateRequest,
    service: ConfigBuilderService = Depends(get_config_builder_service),
) -> ValidationResponse:
    try:
        result = service.validate_alert_config(request.yaml_content)
        return ValidationResponse(
            valid=result["valid"],
            errors=[FieldValidationError(**e) for e in result["errors"]],
        )
    except Exception as exc:
        logger.error(f"[ConfigBuilder] validate_alert_config error: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error during validation",
        )


# ============================================================================
# Generate Endpoints
# ============================================================================


@router.post(
    "/config/control/generate",
    response_model=GenerateResponse,
    summary="Generate control_condition YAML from form data",
    description=(
        "Accept structured control condition data (matching the frontend form fields) "
        "and produce a valid control_condition YAML string. "
        "Reuses ConditionSchema for request validation."
    ),
)
async def generate_control_yaml(
    request: ControlGenerateRequest,
    service: ConfigBuilderService = Depends(get_config_builder_service),
) -> GenerateResponse:
    try:
        # Serialize Pydantic models → plain dicts suitable for yaml.dump
        controls_data = [
            ctrl.model_dump(mode="json", by_alias=True, exclude_none=True) for ctrl in request.controls
        ]
        default_data = [
            ctrl.model_dump(mode="json", by_alias=True, exclude_none=True) for ctrl in request.default_controls
        ]

        yaml_content = service.generate_control_yaml(
            version=request.version,
            model=request.model,
            slave_id=request.slave_id,
            use_default_controls=request.use_default_controls,
            default_controls=default_data,
            controls=controls_data,
        )
        logger.info(
            f"[ConfigBuilder] Generated control YAML for {request.model}/{request.slave_id} "
            f"({len(request.controls)} rule(s))"
        )
        return GenerateResponse(yaml_content=yaml_content)
    except Exception as exc:
        logger.error(f"[ConfigBuilder] generate_control_yaml error: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to generate control config YAML: {exc}",
        )


@router.post(
    "/config/alert/generate",
    response_model=GenerateResponse,
    summary="Generate alert_condition YAML from form data",
    description=(
        "Accept structured alert condition data (matching the frontend form fields) "
        "and produce a valid alert_condition YAML string. "
        "Reuses AlertConditionModel for request validation."
    ),
)
async def generate_alert_yaml(
    request: AlertGenerateRequest,
    service: ConfigBuilderService = Depends(get_config_builder_service),
) -> GenerateResponse:
    try:
        alerts_data = [a.model_dump(mode="json", exclude_none=True) for a in request.alerts]
        default_data = [a.model_dump(mode="json", exclude_none=True) for a in request.default_alerts]

        yaml_content = service.generate_alert_yaml(
            version=request.version,
            model=request.model,
            slave_id=request.slave_id,
            use_default_alerts=request.use_default_alerts,
            default_alerts=default_data,
            alerts=alerts_data,
        )
        logger.info(
            f"[ConfigBuilder] Generated alert YAML for {request.model}/{request.slave_id} "
            f"({len(request.alerts)} alert(s))"
        )
        return GenerateResponse(yaml_content=yaml_content)
    except Exception as exc:
        logger.error(f"[ConfigBuilder] generate_alert_yaml error: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to generate alert config YAML: {exc}",
        )


# ============================================================================
# Diagram Endpoint
# ============================================================================


@router.post(
    "/diagram/generate",
    response_model=DiagramResponse,
    summary="Generate Mermaid flowchart from config YAML",
    description=(
        "Parse a control or alert config YAML and return a Mermaid flowchart string. "
        "The diagram shows the rule/alert tree: conditions, policies, and actions. "
        "Even on parse errors, a minimal error diagram is returned (HTTP 200)."
    ),
)
async def generate_diagram(
    request: DiagramRequest,
    service: ConfigBuilderService = Depends(get_config_builder_service),
) -> DiagramResponse:
    try:
        if request.config_type == "control":
            mermaid = service.generate_control_diagram(request.yaml_content)
        else:
            mermaid = service.generate_alert_diagram(request.yaml_content)

        logger.info(f"[ConfigBuilder] Generated {request.config_type} diagram ({len(mermaid)} chars)")
        return DiagramResponse(mermaid=mermaid)
    except Exception as exc:
        logger.error(f"[ConfigBuilder] generate_diagram error: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate diagram",
        )
