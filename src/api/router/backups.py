"""
Unified Backup Router
"""

import logging

from fastapi import APIRouter, Depends, Query

from api.dependency import get_yaml_manager
from api.model.common import BackupDetailResponse, BackupListResponse, ConfigUpdateResponse
from api.model.enum.config_type import ConfigTypeEnum
from api.service.backup_service import BackupService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/{config_type}", response_model=BackupListResponse, summary="List backups")
async def list_backups(
    config_type: ConfigTypeEnum,
    model: str | None = Query(None, description="Required for pin_mapping"),
    yaml_manager=Depends(get_yaml_manager),
) -> BackupListResponse:
    service = BackupService(yaml_manager=yaml_manager, config_type=config_type, model=model)
    return service.list_backups()


@router.get("/{config_type}/{filename}", response_model=BackupDetailResponse, summary="Preview backup")
async def get_backup_detail(
    config_type: ConfigTypeEnum,
    filename: str,
    model: str | None = Query(None),
    yaml_manager=Depends(get_yaml_manager),
) -> BackupDetailResponse:
    service = BackupService(yaml_manager=yaml_manager, config_type=config_type, model=model)
    return service.get_backup_detail(filename)


@router.post("/{config_type}/{filename}/restore", response_model=ConfigUpdateResponse, summary="Restore backup")
async def restore_backup(
    config_type: ConfigTypeEnum,
    filename: str,
    model: str | None = Query(None),
    yaml_manager=Depends(get_yaml_manager),
) -> ConfigUpdateResponse:
    service = BackupService(yaml_manager=yaml_manager, config_type=config_type, model=model)
    return service.restore_backup(filename)
