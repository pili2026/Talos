"""
YAML Configuration Manager for Talos
Handles reading, writing, and version management of configuration files
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Type, TypeVar

import yaml
from pydantic import BaseModel

from core.schema.constraint_schema import ConstraintConfigSchema
from core.schema.modbus_config_metadata import ConfigMetadata, ConfigSource, calculate_config_checksum
from core.schema.modbus_device_schema import ModbusDeviceFileConfig
from core.util.time_util import TIMEZONE_INFO

logger = logging.getLogger(__name__)

# Type variable for config schemas
T = TypeVar("T", ModbusDeviceFileConfig, ConstraintConfigSchema)


class YAMLManager:
    """
    Manages YAML configuration files with automatic metadata tracking.

    Features:
    - Automatic generation increment
    - Checksum calculation and validation
    - Atomic writes (temp file + rename)
    - Automatic backup creation
    - Backup rotation (keeps last N backups)
    """

    def __init__(self, config_dir: Path | str, backup_count: int = 10):
        """
        Initialize YAML Manager.

        Args:
            config_dir: Directory containing configuration files
            backup_count: Number of backups to keep (default: 10)
        """
        self.config_dir = Path(config_dir)
        self.backup_dir = self.config_dir / "backups"
        self.backup_count = backup_count

        # Ensure directories exist
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(exist_ok=True)

        # Config type to schema mapping
        self.config_schemas: dict[str, Type[BaseModel]] = {
            "modbus_device": ModbusDeviceFileConfig,
            "device_instance": ConstraintConfigSchema,
        }

        logger.info(f"[YAMLManager] Initialized with config_dir={config_dir}, backup_count={backup_count}")

    def read_config(self, config_type: str) -> BaseModel:
        """
        Read and parse configuration file.

        Args:
            config_type: Configuration type (e.g., 'modbus_device', 'device_instance')

        Returns:
            Parsed configuration as Pydantic model

        Raises:
            ValueError: If config_type is unknown
            FileNotFoundError: If config file doesn't exist
            yaml.YAMLError: If YAML is malformed
            pydantic.ValidationError: If config doesn't match schema
        """
        schema_class: type[BaseModel] | None = self.config_schemas.get(config_type)
        if not schema_class:
            raise ValueError(f"Unknown config type: {config_type}")

        path: Path = self.config_dir / f"{config_type}.yml"

        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        logger.debug(f"[YAMLManager] Reading config: {path}")

        try:
            with open(path, "r", encoding="utf-8") as f:
                raw_data = yaml.safe_load(f)

            # Parse with Pydantic
            config: BaseModel = schema_class.model_validate(raw_data)

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

        Features:
        - Auto-increments generation number
        - Updates all metadata fields
        - Calculates and stores checksum
        - Creates backup of old config
        - Uses atomic write (temp file + rename)

        Args:
            config_type: Configuration type
            config: Configuration object to write
            config_source: Source of this change (default: EDGE)
            modified_by: User/system identifier
            create_backup: Whether to create backup of old config

        Raises:
            ValueError: If config_type is unknown
        """
        schema_class: type[BaseModel] | None = self.config_schemas.get(config_type)
        if not schema_class:
            raise ValueError(f"Unknown config type: {config_type}")

        path: Path = self.config_dir / f"{config_type}.yml"

        # Get current generation (if file exists)
        current_gen = 0
        if path.exists():
            try:
                current_config: BaseModel = self.read_config(config_type)
                current_gen = current_config.metadata.generation
            except Exception as e:
                logger.warning(f"[YAMLManager] Cannot read current config for generation: {e}")

        new_gen = current_gen + 1

        # Update metadata
        time_now: str = datetime.now(TIMEZONE_INFO).isoformat()

        config.metadata.generation = new_gen
        config.metadata.config_source = config_source
        config.metadata.last_modified = time_now
        config.metadata.last_modified_by = modified_by
        config.metadata.applied_at = time_now

        # Calculate checksum (exclude metadata)
        data_dict = config.model_dump(by_alias=True, mode="json", exclude={"metadata"})
        config.metadata.checksum = calculate_config_checksum(data_dict)

        logger.info(
            f"[YAMLManager] Updating {config_type}: "
            f"gen {current_gen} → {new_gen}, "
            f"config_source={config_source}, "
            f"by={modified_by}"
        )

        # Backup old file (if exists)
        if create_backup and path.exists():
            self._create_backup(config_type, current_gen)

        # Atomic write
        self._atomic_write(path, config)

        logger.info(f"[YAMLManager] Config {config_type} updated successfully (gen {new_gen})")

    def get_metadata(self, config_type: str) -> ConfigMetadata:
        """
        Get only the metadata from a config file (without parsing the entire config).

        Args:
            config_type: Configuration type

        Returns:
            ConfigMetadata object

        Raises:
            FileNotFoundError: If config file doesn't exist
        """
        path: Path = self.config_dir / f"{config_type}.yml"

        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f)

        metadata_dict = raw_data.get("_metadata", {})
        return ConfigMetadata.model_validate(metadata_dict)

    def list_backups(self, config_type: str) -> list[Path]:
        """
        List all backup files for a config type (newest first).

        Args:
            config_type: Configuration type

        Returns:
            List of backup file paths, sorted by modification time (newest first)
        """
        pattern: str = f"{config_type}_*.yml"
        backup_list: list[Path] = sorted(
            self.backup_dir.glob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        return backup_list

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

        target_path: Path = self.config_dir / f"{config_type}.yml"

        # Create backup of current config before restoring
        if target_path.exists():
            current_config = self.read_config(config_type)
            self._create_backup(config_type, current_config.metadata.generation)

        # Copy backup to main location
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
        schema_class: type[BaseModel] | None = self.config_schemas.get(config_type)
        if not schema_class:
            return False, f"Unknown config type: {config_type}"

        try:
            schema_class.model_validate(config_data)
            return True, None
        except Exception as e:
            return False, str(e)

    def _create_backup(self, config_type: str, generation: int) -> None:
        """
        Create backup of current config file.

        Args:
            config_type: Configuration type
            generation: Current generation number
        """
        config_source_path: Path = self.config_dir / f"{config_type}.yml"

        if not config_source_path.exists():
            return

        timestamp: str = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename: str = f"{config_type}_{timestamp}_gen{generation}.yml"
        backup_path: Path = self.backup_dir / backup_filename

        try:
            shutil.copy2(config_source_path, backup_path)
            logger.debug(f"[YAMLManager] Created backup: {backup_filename}")

            # Cleanup old backups
            self._cleanup_old_backups(config_type)

        except Exception as e:
            logger.error(f"[YAMLManager] Backup creation failed: {e}")
            # Don't raise - backup failure shouldn't stop config update

    def _cleanup_old_backups(self, config_type: str) -> None:
        """
        Remove old backups, keeping only the most recent N.

        Args:
            config_type: Configuration type
        """
        try:
            # Find all backups for this config type
            pattern: str = f"{config_type}_*.yml"
            backup_list: list[Path] = sorted(
                self.backup_dir.glob(pattern),
                key=lambda p: p.stat().st_mtime,
                reverse=True,  # Newest first
            )

            # Remove old backups
            removed_count = 0
            for old_backup in backup_list[self.backup_count :]:
                old_backup.unlink()
                removed_count += 1

            if removed_count > 0:
                logger.debug(f"[YAMLManager] Cleaned up {removed_count} old backups")

        except Exception as e:
            logger.error(f"[YAMLManager] Backup cleanup failed: {e}")

    def _atomic_write(self, path: Path, config: BaseModel) -> None:
        """
        Atomically write config to file using temp file + rename.

        Args:
            path: Target file path
            config: Configuration to write

        Raises:
            Exception: If write fails
        """
        temp_path = path.with_suffix(".tmp")

        try:
            # Serialize config with aliases (_metadata, buses, devices)
            data_dict = config.model_dump(by_alias=True, mode="json")

            # Write to temp file
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

            # Atomic rename
            temp_path.replace(path)

            logger.debug(f"[YAMLManager] Atomic write completed: {path}")

        except Exception as e:
            # Clean up temp file on error
            if temp_path.exists():
                temp_path.unlink()

            logger.error(f"[YAMLManager] Atomic write failed: {e}")
            raise
