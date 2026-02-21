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
from core.schema.system_config_schema import SystemConfigFileSchema
from core.util.time_util import TIMEZONE_INFO

logger = logging.getLogger(__name__)

T = TypeVar("T", ModbusDeviceFileConfig, ConstraintConfigSchema)


class YAMLManager:
    """
    Manages YAML configuration files with automatic metadata tracking.

    Features:
    - Automatic generation increment
    - Checksum calculation and validation
    - Atomic writes (temp file + rename)
    - Automatic backup creation per config type (in subdirectories)
    - Backup rotation (keeps last N backups)
    """

    def __init__(self, config_dir: Path | str, backup_count: int = 10):
        """
        Initialize YAML Manager.

        Args:
            config_dir: Directory containing configuration files
            backup_count: Number of backups to keep per config type (default: 10)
        """
        self.config_dir = Path(config_dir)
        self.backup_dir = self.config_dir / "backups"
        self.backup_count = backup_count

        # Ensure base directories exist
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(exist_ok=True)

        # Config type to schema mapping
        self.config_schemas: dict[str, Type[BaseModel]] = {
            "modbus_device": ModbusDeviceFileConfig,
            "device_instance": ConstraintConfigSchema,
            "system_config": SystemConfigFileSchema,
        }

        logger.info(f"[YAMLManager] Initialized with config_dir={config_dir}, backup_count={backup_count}")

    # ============================================================================
    # Public API
    # ============================================================================

    def read_config(self, config_type: str) -> BaseModel:
        """
        Read and parse configuration file.

        Args:
            config_type: Configuration type (e.g., 'modbus_device', 'system_config')

        Returns:
            Parsed configuration as Pydantic model

        Raises:
            ValueError: If config_type is unknown
            FileNotFoundError: If config file doesn't exist
            yaml.YAMLError: If YAML is malformed
            pydantic.ValidationError: If config doesn't match schema
        """
        schema_class = self.config_schemas.get(config_type)
        if not schema_class:
            raise ValueError(f"Unknown config type: {config_type}")

        path = self.config_dir / f"{config_type}.yml"
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        logger.debug(f"[YAMLManager] Reading config: {path}")

        try:
            with open(path, "r", encoding="utf-8") as f:
                raw_data = yaml.safe_load(f)

            config = schema_class.model_validate(raw_data)

            logger.info(
                f"[YAMLManager] Loaded {config_type}: "
                f"generation={config.metadata.generation}, "
                f"config_source={config.metadata.config_source}"
            )

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
    ) -> None:
        """
        Update configuration file with automatic metadata management.

        Args:
            config_type: Configuration type
            config: Configuration object to write
            config_source: Source of this change (default: EDGE)
            modified_by: User/system identifier
            create_backup: Whether to create backup of old config
        """
        schema_class = self.config_schemas.get(config_type)
        if not schema_class:
            raise ValueError(f"Unknown config type: {config_type}")

        path = self.config_dir / f"{config_type}.yml"

        # Get current generation
        current_gen = 0
        if path.exists():
            try:
                current_config = self.read_config(config_type)
                current_gen = current_config.metadata.generation
            except Exception as e:
                logger.warning(f"[YAMLManager] Cannot read current config for generation: {e}")

        new_gen = current_gen + 1

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
            f"[YAMLManager] Updating {config_type}: "
            f"gen {current_gen} → {new_gen}, "
            f"config_source={config_source}, "
            f"by={modified_by}"
        )

        # Backup old file
        if create_backup and path.exists():
            self._create_backup(config_type, current_gen)

        # Atomic write
        self._atomic_write(path, config)

        logger.info(f"[YAMLManager] Config {config_type} updated successfully (gen {new_gen})")

    def get_metadata(self, config_type: str) -> ConfigMetadata:
        """
        Get only the metadata from a config file.

        Args:
            config_type: Configuration type

        Returns:
            ConfigMetadata object
        """
        path = self.config_dir / f"{config_type}.yml"
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f)

        metadata_dict = raw_data.get("_metadata", {})
        return ConfigMetadata.model_validate(metadata_dict)

    def list_backups(self, config_type: ConfigTypeEnum) -> list[Path]:
        """
        List all backup files for a config type (newest first).

        Backups are stored in: backups/{config_type}/

        Args:
            config_type: Configuration type

        Returns:
            List of backup file paths, sorted by modification time (newest first)
        """
        backup_subdir = self._get_backup_dir(config_type)
        return sorted(
            backup_subdir.glob(f"{config_type}_*.yml"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    def restore_backup(self, backup_path: Path, config_type: str) -> None:
        """
        Restore a config from a backup file.

        Args:
            backup_path: Path to backup file
            config_type: Configuration type

        Raises:
            FileNotFoundError: If backup doesn't exist
        """
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        target_path = self.config_dir / f"{config_type}.yml"

        # Backup current config before restoring
        if target_path.exists():
            current_config = self.read_config(config_type)
            self._create_backup(config_type, current_config.metadata.generation)

        shutil.copy2(backup_path, target_path)
        logger.info(f"[YAMLManager] Restored {config_type} from backup: {backup_path.name}")

    def validate_config(self, config_type: str, config_data: dict) -> tuple[bool, str | None]:
        """
        Validate config data against schema without writing to file.

        Args:
            config_type: Configuration type
            config_data: Raw config dictionary

        Returns:
            Tuple of (is_valid, error_message)
        """
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

    def _get_backup_dir(self, config_type: ConfigTypeEnum) -> Path:
        """
        Get or create backup subdirectory for a specific config type.

        Structure: backups/{config_type}/

        Args:
            config_type: Configuration type

        Returns:
            Path to backup subdirectory
        """
        backup_subdir = self.backup_dir / config_type
        backup_subdir.mkdir(exist_ok=True)
        return backup_subdir

    def _create_backup(self, config_type: ConfigTypeEnum, generation: int) -> None:
        """
        Create backup of current config file in its subdirectory.

        Args:
            config_type: Configuration type
            generation: Current generation number
        """
        config_source_path = self.config_dir / f"{config_type}.yml"
        if not config_source_path.exists():
            return

        backup_subdir = self._get_backup_dir(config_type)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"{config_type}_{timestamp}_gen{generation}.yml"
        backup_path = backup_subdir / backup_filename

        try:
            shutil.copy2(config_source_path, backup_path)
            logger.debug(f"[YAMLManager] Created backup: {backup_subdir.name}/{backup_filename}")
            self._cleanup_old_backups(config_type)
        except Exception as e:
            logger.error(f"[YAMLManager] Backup creation failed: {e}")

    def _cleanup_old_backups(self, config_type: str) -> None:
        """
        Remove old backups, keeping only the most recent N.

        Args:
            config_type: Configuration type
        """
        try:
            backup_subdir = self._get_backup_dir(config_type)
            backup_list = sorted(
                backup_subdir.glob(f"{config_type}_*.yml"),
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
        """
        Atomically write config to file using temp file + rename.

        Args:
            path: Target file path
            config: Configuration to write
        """
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
