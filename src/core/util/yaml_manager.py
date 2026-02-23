"""
YAML Configuration Manager for Talos
Handles reading, writing, and version management of configuration files
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Type, TypeVar

import yaml
from pydantic import BaseModel

from api.model.enum.config_type import ConfigTypeEnum
from core.schema.config_metadata import ConfigMetadata, ConfigSource, calculate_config_checksum
from core.schema.constraint_schema import ConstraintConfigSchema
from core.schema.modbus_device_schema import ModbusDeviceFileConfig
from core.schema.pin_mapping_schema import PinMappingConfig
from core.schema.system_config_schema import SystemConfigFileSchema
from core.util.time_util import TIMEZONE_INFO

logger = logging.getLogger(__name__)

T = TypeVar("T", ModbusDeviceFileConfig, ConstraintConfigSchema)


class YAMLManager:
    def __init__(self, config_dir: Path | str, backup_count: int = 10):
        self.config_dir = Path(config_dir)
        self.backup_dir = self.config_dir / "backups"
        self.backup_count = backup_count

        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(exist_ok=True)

        self.config_schemas: dict[str, Type[BaseModel]] = {
            "modbus_device": ModbusDeviceFileConfig,
            "device_instance_config": ConstraintConfigSchema,
            "system_config": SystemConfigFileSchema,
            "pin_mapping": PinMappingConfig,
        }

        logger.info(f"[YAMLManager] Initialized with config_dir={config_dir}, backup_count={backup_count}")

    # ============================================================================
    # Public API
    # ============================================================================

    def read_config(self, config_type: str, model: str | None = None) -> BaseModel:
        schema_class = self.config_schemas.get(config_type)
        if not schema_class:
            raise ValueError(f"Unknown config type: {config_type}")

        path = self._resolve_path(config_type, model)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        logger.debug(f"[YAMLManager] Reading config: {path}")

        try:
            with open(path, "r", encoding="utf-8") as f:
                raw_data = yaml.safe_load(f)

            config = schema_class.model_validate(raw_data)

            gen = config.metadata.generation if config.metadata else "N/A"
            logger.info(f"[YAMLManager] Loaded {config_type}: generation={gen}")

            return config

        except yaml.YAMLError as e:
            logger.error(f"[YAMLManager] YAML parse error in {path}: {e}")
            raise
        except Exception as e:
            logger.error(f"[YAMLManager] Failed to read config {path}: {e}")
            raise

    def update_config(
        self,
        config_type: str,
        config: BaseModel,
        config_source: ConfigSource = ConfigSource.EDGE,
        modified_by: str | None = None,
        create_backup: bool = True,
        model: str | None = None,
    ) -> None:
        schema_class = self.config_schemas.get(config_type)
        if not schema_class:
            raise ValueError(f"Unknown config type: {config_type}")

        path = self._resolve_path(config_type, model)

        # Get current generation
        current_gen = 0
        if path.exists():
            try:
                current_config = self.read_config(config_type, model)
                if current_config.metadata:
                    current_gen = current_config.metadata.generation
            except Exception as e:
                logger.warning(f"[YAMLManager] Cannot read current config for generation: {e}")

        new_gen = current_gen + 1

        # Ensure metadata exists
        if config.metadata is None:
            config.metadata = ConfigMetadata()

        # Update metadata
        time_now = datetime.now(TIMEZONE_INFO).isoformat()
        config.metadata.generation = new_gen
        config.metadata.config_source = config_source
        config.metadata.last_modified = time_now
        config.metadata.last_modified_by = modified_by
        config.metadata.applied_at = time_now

        # Calculate checksum
        data_dict = config.model_dump(by_alias=True, mode="json", exclude={"metadata"})
        config.metadata.checksum = calculate_config_checksum(data_dict)

        logger.info(
            f"[YAMLManager] Updating {config_type}"
            + (f"/{model}" if model else "")
            + f": gen {current_gen} → {new_gen}, source={config_source}, by={modified_by}"
        )

        # Backup old file
        if create_backup and path.exists():
            self._create_backup(config_type, current_gen, model)

        # Atomic write
        self._atomic_write(path, config)

        logger.info(f"[YAMLManager] Config {config_type} updated successfully (gen {new_gen})")

    def get_metadata(self, config_type: str, model: str | None = None) -> ConfigMetadata:
        path = self._resolve_path(config_type, model)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f)

        metadata_dict = raw_data.get("_metadata", {})
        return ConfigMetadata.model_validate(metadata_dict)

    def list_backups(self, config_type: ConfigTypeEnum, model: str | None = None) -> list[Path]:
        backup_subdir = self._get_backup_dir(config_type)

        if config_type == "pin_mapping" and model:
            pattern = f"pin_mapping_{model.lower()}_*.yml"
        else:
            pattern = f"{config_type}_*.yml"

        return sorted(
            backup_subdir.glob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    def restore_backup(
        self,
        backup_path: Path,
        config_type: str,
        model: str | None = None,
    ) -> None:
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        target_path = self._resolve_path(config_type, model)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Backup current before restoring
        if target_path.exists():
            try:
                current_config = self.read_config(config_type, model)
                gen = current_config.metadata.generation if current_config.metadata else 0
                self._create_backup(config_type, gen, model)
            except Exception as e:
                logger.warning(f"[YAMLManager] Could not backup before restore: {e}")

        shutil.copy2(backup_path, target_path)
        logger.info(f"[YAMLManager] Restored {config_type} from backup: {backup_path.name}")

    def validate_config(self, config_type: str, config_data: dict) -> tuple[bool, str | None]:
        schema_class = self.config_schemas.get(config_type)
        if not schema_class:
            return False, f"Unknown config type: {config_type}"

        try:
            schema_class.model_validate(config_data)
            return True, None
        except Exception as e:
            return False, str(e)

    # ============================================================================
    # Private Helpers
    # ============================================================================

    def _resolve_path(self, config_type: str, model: str | None = None) -> Path:
        """
        Resolve the file path for a given config type.

        For pin_mapping: res/pin_mapping/{model}_default.yml
        For others:      res/{config_type}.yml
        """
        if config_type == "pin_mapping":
            if not model:
                raise ValueError("model is required for pin_mapping config type")
            path = self.config_dir / "pin_mapping" / f"{model.lower()}_default.yml"
            path.parent.mkdir(parents=True, exist_ok=True)
            return path
        return self.config_dir / f"{config_type}.yml"

    def _get_backup_dir(self, config_type: ConfigTypeEnum) -> Path:
        backup_subdir = self.backup_dir / config_type
        backup_subdir.mkdir(exist_ok=True)
        return backup_subdir

    def _create_backup(self, config_type: str, generation: int, model: str | None = None) -> None:
        config_source_path = self._resolve_path(config_type, model)
        if not config_source_path.exists():
            return

        backup_subdir = self._get_backup_dir(config_type)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if config_type == "pin_mapping" and model:
            backup_filename = f"pin_mapping_{model.lower()}_{timestamp}_gen{generation}.yml"
        else:
            backup_filename = f"{config_type}_{timestamp}_gen{generation}.yml"

        backup_path = backup_subdir / backup_filename

        try:
            shutil.copy2(config_source_path, backup_path)
            logger.debug(f"[YAMLManager] Created backup: {backup_subdir.name}/{backup_filename}")
            self._cleanup_old_backups(config_type, model)
        except Exception as e:
            logger.error(f"[YAMLManager] Backup creation failed: {e}")

    def _cleanup_old_backups(self, config_type: str, model: str | None = None) -> None:
        try:
            backup_subdir = self._get_backup_dir(config_type)

            if config_type == "pin_mapping" and model:
                pattern = f"pin_mapping_{model.lower()}_*.yml"
            else:
                pattern = f"{config_type}_*.yml"

            backup_list = sorted(
                backup_subdir.glob(pattern),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )

            removed_count = 0
            for old_backup in backup_list[self.backup_count :]:
                old_backup.unlink()
                removed_count += 1

            if removed_count > 0:
                logger.debug(f"[YAMLManager] Cleaned up {removed_count} old backups for {config_type}")

        except Exception as e:
            logger.error(f"[YAMLManager] Backup cleanup failed: {e}")

    def _atomic_write(self, path: Path, config: BaseModel) -> None:
        temp_path = path.with_suffix(".tmp")

        try:
            data_dict = config.model_dump(by_alias=True, mode="json")

            with open(temp_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(
                    data_dict,
                    f,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=False,
                    width=120,
                    indent=2,
                )

            temp_path.replace(path)
            logger.debug(f"[YAMLManager] Atomic write completed: {path}")

        except Exception as e:
            if temp_path.exists():
                temp_path.unlink()
            logger.error(f"[YAMLManager] Atomic write failed: {e}")
            raise
