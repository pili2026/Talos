"""
Backup Service
Unified backup operations for all config types
"""

import logging
import re
from datetime import datetime

import yaml
from fastapi import HTTPException, status

from api.model.common import BackupDetailResponse, BackupInfo, BackupListResponse, ConfigUpdateResponse
from api.model.enum.config_type import ConfigTypeEnum
from api.model.enums import ResponseStatus
from core.util.yaml_manager import YAMLManager

logger = logging.getLogger(__name__)


class BackupService:

    def __init__(self, yaml_manager: YAMLManager, config_type: ConfigTypeEnum, model: str | None = None):
        self._yaml_manager = yaml_manager
        self._config_type = config_type
        self._model = model

    def list_backups(self) -> BackupListResponse:
        try:
            backup_paths = self._yaml_manager.list_backups(
                self._config_type,
                model=self._model,
            )

            backups = []
            for backup_path in backup_paths:
                match = re.search(r"_gen(\d+)\.yml$", backup_path.name)
                generation = int(match.group(1)) if match else None
                stat = backup_path.stat()
                backups.append(
                    BackupInfo(
                        filename=backup_path.name,
                        generation=generation,
                        created_at=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        size_bytes=stat.st_size,
                    )
                )

            return BackupListResponse(
                status=ResponseStatus.SUCCESS,
                backups=backups,
                total=len(backups),
            )

        except Exception as e:
            logger.error(f"[BackupService] Failed to list backups for {self._config_type}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to list backups: {str(e)}",
            ) from e

    def get_backup_detail(self, filename: str) -> BackupDetailResponse:
        try:
            backup_path = self._yaml_manager.backup_dir / self._config_type / filename

            if not backup_path.exists():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Backup '{filename}' not found",
                )

            with open(backup_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)

            metadata = raw.pop("_metadata", {})

            return BackupDetailResponse(
                status=ResponseStatus.SUCCESS,
                filename=filename,
                metadata=metadata,
                content=raw,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[BackupService] Failed to read backup detail: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to read backup: {str(e)}",
            ) from e

    def restore_backup(self, filename: str) -> ConfigUpdateResponse:
        try:
            backup_path = self._yaml_manager.backup_dir / self._config_type / filename

            if not backup_path.exists():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Backup '{filename}' not found")

            self._yaml_manager.restore_backup(backup_path, self._config_type, model=self._model)

            config = self._yaml_manager.read_config(self._config_type, model=self._model)

            logger.info(f"[BackupService] Restored {self._config_type} from '{filename}'")

            return ConfigUpdateResponse(
                status=ResponseStatus.SUCCESS,
                message=f"Restored from backup '{filename}'",
                generation=config.metadata.generation if config.metadata else None,
                checksum=config.metadata.checksum if config.metadata else None,
                modified_at=config.metadata.last_modified if config.metadata else None,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[BackupService] Failed to restore backup: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to restore backup: {str(e)}",
            ) from e
