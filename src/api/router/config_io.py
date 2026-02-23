"""
Config Import/Export Router
"""

import logging
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, ValidationError

from api.dependency import get_yaml_manager
from api.model.common import ConfigUpdateResponse
from api.model.enum.config_type import ConfigTypeEnum
from api.model.enums import ResponseStatus
from core.schema.config_metadata import ConfigSource
from core.schema.pin_mapping_schema import PinMappingConfig
from core.util.yaml_manager import YAMLManager

logger = logging.getLogger(__name__)

export_router = APIRouter()
import_router = APIRouter()

FILENAMES: dict[str, str] = {
    "modbus_device": "modbus_device.yml",
    "system_config": "system_config.yml",
    "device_instance_config": "device_instance_config.yml",
    "alert_config": "alert_condition.yml",
    "control_config": "control_condition.yml",
}


@export_router.get("/{config_type}", summary="Export config as YAML file")
async def export_config(
    config_type: ConfigTypeEnum,
    model: str | None = Query(None, description="Required for pin_mapping"),
    yaml_manager: YAMLManager = Depends(get_yaml_manager),
) -> Response:
    if config_type == ConfigTypeEnum.PIN_MAPPING:
        if not model:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="model query param is required for pin_mapping",
            )
        override_path = yaml_manager.config_dir / "pin_mapping" / f"{model.lower().replace('-', '_')}_default.yml"
        template_path = (
            yaml_manager.config_dir / "template" / "pin_mapping" / f"{model.lower().replace('-', '_')}_default.yml"
        )

        if override_path.exists():
            content = override_path.read_bytes()
        elif template_path.exists():
            content = template_path.read_bytes()
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No pin mapping found for model: {model}",
            )

        return Response(
            content=content,
            media_type="application/x-yaml",
            headers={"Content-Disposition": f"attachment; filename={model.lower()}_default.yml"},
        )

    config_path: Path = yaml_manager.config_dir / f"{config_type}.yml"
    if not config_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Config '{config_type}' not found",
        )

    with open(config_path, "rb") as f:
        content: bytes = f.read()

    return Response(
        content=content,
        media_type="application/x-yaml",
        headers={
            "Content-Disposition": f"attachment; filename={FILENAMES.get(config_type, f'{config_type}.yml')}",
        },
    )


@import_router.post("/{config_type}", response_model=ConfigUpdateResponse, summary="Import config from YAML file")
async def import_config(
    config_type: ConfigTypeEnum,
    model: str | None = Query(None, description="Required for pin_mapping"),
    file: UploadFile = File(...),
    yaml_manager: YAMLManager = Depends(get_yaml_manager),
) -> ConfigUpdateResponse:
    content: bytes = await file.read()

    if config_type == ConfigTypeEnum.PIN_MAPPING:
        if not model:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="model query param is required for pin_mapping",
            )
        try:
            raw = yaml.safe_load(content)
            if not isinstance(raw, dict):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Invalid YAML: root must be a mapping",
                )
            config = PinMappingConfig(**raw)
        except ValidationError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Schema validation failed: {e}",
            ) from e
        except yaml.YAMLError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid YAML: {e}",
            ) from e

        yaml_manager.update_config(
            "pin_mapping",
            config,
            config_source=ConfigSource.EDGE,
            model=model,
        )
        saved = yaml_manager.read_config("pin_mapping", model=model)

        return ConfigUpdateResponse(
            status=ResponseStatus.SUCCESS,
            message=f"Pin mapping '{model}' imported successfully",
            generation=saved.metadata.generation if saved.metadata else None,
            checksum=saved.metadata.checksum if saved.metadata else None,
            modified_at=saved.metadata.last_modified if saved.metadata else None,
        )

    try:
        parsed = yaml.safe_load(content)
        if not isinstance(parsed, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Invalid YAML: root must be a mapping",
            )
    except yaml.YAMLError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid YAML: {str(e)}",
        ) from e

    is_valid, error_msg = yaml_manager.validate_config(config_type, parsed)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Config validation failed: {error_msg}",
        )

    try:
        current: BaseModel = yaml_manager.read_config(config_type)
        yaml_manager._create_backup(config_type, current.metadata.generation)
    except Exception as e:
        logger.warning(f"[config_io] Could not create backup before import: {e}")

    config_path: Path = yaml_manager.config_dir / f"{config_type}.yml"
    with open(config_path, "wb") as f:
        f.write(content)

    saved: BaseModel = yaml_manager.read_config(config_type)

    return ConfigUpdateResponse(
        status=ResponseStatus.SUCCESS,
        message=f"Config '{config_type}' imported successfully",
        generation=saved.metadata.generation,
        checksum=saved.metadata.checksum,
        modified_at=saved.metadata.last_modified,
    )
