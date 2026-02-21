"""
Config Import/Export Router
Unified export/import operations for all config types
"""

import logging
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel

from api.dependency import get_yaml_manager
from api.model.common import ConfigUpdateResponse
from api.model.enum.config_type import ConfigTypeEnum
from api.model.enums import ResponseStatus
from core.util.yaml_manager import YAMLManager

logger = logging.getLogger(__name__)

export_router = APIRouter()
import_router = APIRouter()


FILENAMES: dict[str, str] = {
    "modbus_device": "modbus_device.yml",
    "system_config": "system_config.yml",
}


@export_router.get("/{config_type}", summary="Export config as YAML file")
async def export_config(
    config_type: ConfigTypeEnum,
    yaml_manager: YAMLManager = Depends(get_yaml_manager),
) -> Response:
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
            "Content-Disposition": f"attachment; filename={FILENAMES[config_type]}",
        },
    )


@import_router.post("/{config_type}", response_model=ConfigUpdateResponse, summary="Import config from YAML file")
async def import_config(
    config_type: ConfigTypeEnum,
    file: UploadFile = File(...),
    yaml_manager: YAMLManager = Depends(get_yaml_manager),
) -> ConfigUpdateResponse:
    content: bytes = await file.read()

    # Validation steps
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

    # Perform schema validation using YAMLManager
    is_valid, error_msg = yaml_manager.validate_config(config_type, parsed)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Config validation failed: {error_msg}",
        )

    # Backup current config before overwriting
    try:
        current_config_model: BaseModel = yaml_manager.read_config(config_type)
        yaml_manager._create_backup(config_type, current_config_model.metadata.generation)
    except Exception as e:
        logger.warning(f"[config_io] Could not create backup before import: {e}")

    # Write new config to file
    config_path: Path = yaml_manager.config_dir / f"{config_type}.yml"
    with open(config_path, "wb") as f:
        f.write(content)

    config: BaseModel = yaml_manager.read_config(config_type)
    logger.info(f"[config_io] Imported {config_type} from uploaded file")

    return ConfigUpdateResponse(
        status=ResponseStatus.SUCCESS,
        message=f"Config '{config_type}' imported successfully",
        generation=config.metadata.generation,
        checksum=config.metadata.checksum,
        modified_at=config.metadata.last_modified,
    )
