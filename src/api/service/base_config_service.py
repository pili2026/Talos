"""
Base Config Service
Shared backup logic for all config services
"""

import logging
import re
from datetime import datetime

from fastapi import HTTPException, status

from api.model.common import BackupInfo, BackupListResponse
from api.model.enums import ResponseStatus
from core.util.yaml_manager import YAMLManager

logger = logging.getLogger(__name__)


class BaseConfigService:
    """
    Base class providing shared backup operations for all config services.
    Subclasses pass config_type to target their specific yml file.
    """

    def __init__(self, yaml_manager: YAMLManager, config_type: str):
        self._yaml_manager = yaml_manager
        self._config_type = config_type

    def list_backups(self) -> BackupListResponse:
        try:
            backup_paths = self._yaml_manager.list_backups(self._config_type)

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
            logger.error(f"[{self.__class__.__name__}] Failed to list backups: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to list backups: {str(e)}",
            ) from e

    def _do_restore(self, filename: str) -> None:
        """
        Shared restore logic. Subclasses call this then handle their own post-restore logic.
        """
        backup_path = self._yaml_manager.backup_dir / filename

        if not backup_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Backup '{filename}' not found",
            )

        self._yaml_manager.restore_backup(backup_path, self._config_type)
        logger.info(f"[{self.__class__.__name__}] Restored '{self._config_type}' from backup '{filename}'")
