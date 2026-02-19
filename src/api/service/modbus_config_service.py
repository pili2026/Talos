"""
Configuration Management Service
Business logic for modbus device configuration with version control
"""

import logging
import re
from datetime import datetime

from fastapi import HTTPException, status

from api.model.enums import ResponseStatus
from api.model.modbus_config import (
    BackupInfo,
    BackupListResponse,
    ConfigUpdateResponse,
    MetadataInfo,
    MetadataResponse,
    ModbusBusCreateRequest,
    ModbusBusInfo,
    ModbusConfigResponse,
    ModbusDeviceCreateRequest,
    ModbusDeviceInfo,
)
from core.schema.modbus_config_metadata import ConfigSource
from core.schema.modbus_device_schema import ModbusBusConfig, ModbusDeviceConfig
from core.util.config_manager import ConfigManager
from core.util.yaml_manager import YAMLManager

logger = logging.getLogger(__name__)


class ConfigService:
    """
    Configuration Management Service

    Provides business logic for managing modbus device configurations
    with automatic version control, backup, and metadata management.
    """

    def __init__(self, yaml_manager: YAMLManager, config_manager: ConfigManager | None = None):
        """
        Initialize ConfigService.

        Args:
            yaml_manager: YAMLManager instance for file operations
            config_manager: ConfigManager instance (optional, for future use)
        """
        self.yaml_manager = yaml_manager
        self.config_manager = config_manager

    # ============================================================================
    # Metadata Operations
    # ============================================================================

    async def get_metadata(self) -> MetadataResponse:
        """
        Get configuration metadata.

        Returns:
            MetadataResponse containing current metadata
        """
        try:
            metadata = self.yaml_manager.get_metadata("modbus_device")

            metadata_info = MetadataInfo(
                generation=metadata.generation,
                source=metadata.config_source.value,  # ConfigSource is an Enum
                last_modified=metadata.last_modified,
                last_modified_by=metadata.last_modified_by,
                checksum=metadata.checksum,
                applied_at=metadata.applied_at,
                cloud_sync_id=metadata.cloud_sync_id,
            )

            return MetadataResponse(status=ResponseStatus.SUCCESS, metadata=metadata_info)

        except FileNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration file not found") from e
        except Exception as e:
            logger.error(f"[ConfigService] Failed to get metadata: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to retrieve metadata: {str(e)}"
            ) from e

    # ============================================================================
    # Configuration Operations
    # ============================================================================

    async def get_config(self) -> ModbusConfigResponse:
        """
        Get complete modbus configuration.

        Returns:
            ModbusConfigResponse containing buses, devices, and metadata
        """
        try:
            config = self.yaml_manager.read_config("modbus_device")

            # Convert metadata
            metadata_info = MetadataInfo(
                generation=config.metadata.generation,
                source=config.metadata.config_source.value,  # ConfigSource is an Enum
                last_modified=config.metadata.last_modified,
                last_modified_by=config.metadata.last_modified_by,
                checksum=config.metadata.checksum,
                applied_at=config.metadata.applied_at,
                cloud_sync_id=config.metadata.cloud_sync_id,
            )

            # Convert buses
            buses = {
                name: ModbusBusInfo(name=name, port=bus.port, baudrate=bus.baudrate, timeout=bus.timeout)
                for name, bus in config.bus_dict.items()
            }

            # Convert devices
            devices = [
                ModbusDeviceInfo(
                    model=device.model,
                    type=device.type,
                    model_file=device.model_file,
                    slave_id=device.slave_id,
                    bus=device.bus,
                    port=device.port,
                    baudrate=device.baudrate,
                    timeout=device.timeout,
                    modes=device.modes,
                )
                for device in config.device_list
            ]

            return ModbusConfigResponse(
                status=ResponseStatus.SUCCESS, metadata=metadata_info, buses=buses, devices=devices
            )

        except FileNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration file not found") from e
        except Exception as e:
            logger.error(f"[ConfigService] Failed to get config: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to retrieve configuration: {str(e)}"
            ) from e

    # ============================================================================
    # Bus Operations
    # ============================================================================

    async def create_or_update_bus(
        self, bus_name: str, bus_request: ModbusBusCreateRequest, user: str
    ) -> ConfigUpdateResponse:
        """
        Create or update a modbus bus.

        Args:
            bus_name: Bus identifier
            bus_request: Bus configuration
            user: User making the change

        Returns:
            ConfigUpdateResponse with operation result
        """
        try:
            config = self.yaml_manager.read_config("modbus_device")

            # Create/update bus
            config.bus_dict[bus_name] = ModbusBusConfig(
                port=bus_request.port, baudrate=bus_request.baudrate, timeout=bus_request.timeout
            )

            # Save with version management
            self.yaml_manager.update_config("modbus_device", config, config_source=ConfigSource.EDGE, modified_by=user)

            logger.info(f"[ConfigService] Bus '{bus_name}' created/updated by {user}")

            return ConfigUpdateResponse(
                status=ResponseStatus.SUCCESS,
                message=f"Bus '{bus_name}' created/updated successfully",
                generation=config.metadata.generation,
                checksum=config.metadata.checksum,
                modified_at=config.metadata.last_modified,
            )

        except Exception as e:
            logger.error(f"[ConfigService] Failed to create/update bus: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create/update bus: {str(e)}"
            ) from e

    async def delete_bus(self, bus_name: str, user: str) -> ConfigUpdateResponse:
        """
        Delete a modbus bus.

        Args:
            bus_name: Bus identifier
            user: User making the change

        Returns:
            ConfigUpdateResponse with operation result
        """
        try:
            config = self.yaml_manager.read_config("modbus_device")

            # Check if bus exists
            if bus_name not in config.bus_dict:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Bus '{bus_name}' not found")

            # Check if any device is using this bus
            devices_using_bus = [f"{d.model}_{d.slave_id}" for d in config.device_list if d.bus == bus_name]

            if devices_using_bus:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Cannot delete bus '{bus_name}': in use by devices {devices_using_bus}",
                )

            # Delete bus
            del config.bus_dict[bus_name]

            # Save
            self.yaml_manager.update_config("modbus_device", config, config_source=ConfigSource.EDGE, modified_by=user)

            logger.info(f"[ConfigService] Bus '{bus_name}' deleted by {user}")

            return ConfigUpdateResponse(
                status=ResponseStatus.SUCCESS,
                message=f"Bus '{bus_name}' deleted successfully",
                generation=config.metadata.generation,
                checksum=config.metadata.checksum,
                modified_at=config.metadata.last_modified,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[ConfigService] Failed to delete bus: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to delete bus: {str(e)}"
            ) from e

    # ============================================================================
    # Device Operations
    # ============================================================================

    async def create_or_update_device(
        self, device_request: ModbusDeviceCreateRequest, user: str
    ) -> ConfigUpdateResponse:
        """
        Create or update a modbus device.

        Args:
            device_request: Device configuration
            user: User making the change

        Returns:
            ConfigUpdateResponse with operation result
        """
        try:
            config = self.yaml_manager.read_config("modbus_device")

            # Validate bus exists
            if device_request.bus not in config.bus_dict:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Bus '{device_request.bus}' not found. Available: {list(config.bus_dict.keys())}",
                )

            # Create device config
            new_device = ModbusDeviceConfig(
                model=device_request.model,
                type=device_request.type,
                model_file=device_request.model_file,
                slave_id=device_request.slave_id,
                bus=device_request.bus,
                modes=device_request.modes,
            )

            # Check if exists
            existing_index = self._find_device_index(config.device_list, device_request.model, device_request.slave_id)

            if existing_index is not None:
                config.device_list[existing_index] = new_device
                action = "updated"
            else:
                config.device_list.append(new_device)
                action = "created"

            # Save
            self.yaml_manager.update_config("modbus_device", config, config_source=ConfigSource.EDGE, modified_by=user)

            logger.info(
                f"[ConfigService] Device {device_request.model}_{device_request.slave_id} " f"{action} by {user}"
            )

            return ConfigUpdateResponse(
                status=ResponseStatus.SUCCESS,
                message=f"Device {device_request.model} (slave_id={device_request.slave_id}) {action}",
                generation=config.metadata.generation,
                checksum=config.metadata.checksum,
                modified_at=config.metadata.last_modified,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[ConfigService] Failed to create/update device: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create/update device: {str(e)}"
            ) from e

    async def delete_device(self, model: str, slave_id: int, user: str) -> ConfigUpdateResponse:
        """
        Delete a modbus device.

        Args:
            model: Device model
            slave_id: Device slave ID
            user: User making the change

        Returns:
            ConfigUpdateResponse with operation result
        """
        try:
            config = self.yaml_manager.read_config("modbus_device")

            device_index = self._find_device_index(config.device_list, model, slave_id)

            if device_index is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail=f"Device {model}_{slave_id} not found"
                )

            config.device_list.pop(device_index)

            self.yaml_manager.update_config("modbus_device", config, config_source=ConfigSource.EDGE, modified_by=user)

            logger.info(f"[ConfigService] Device {model}_{slave_id} deleted by {user}")

            return ConfigUpdateResponse(
                status=ResponseStatus.SUCCESS,
                message=f"Device {model} (slave_id={slave_id}) deleted",
                generation=config.metadata.generation,
                checksum=config.metadata.checksum,
                modified_at=config.metadata.last_modified,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[ConfigService] Failed to delete device: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to delete device: {str(e)}"
            ) from e

    # ============================================================================
    # Backup Operations
    # ============================================================================

    async def list_backups(self) -> BackupListResponse:
        """
        List configuration backups.

        Returns:
            BackupListResponse with backup list
        """
        try:
            backup_paths = self.yaml_manager.list_backups("modbus_device")

            backups = []
            for backup_path in backup_paths:
                # Extract generation
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

            return BackupListResponse(status=ResponseStatus.SUCCESS, backups=backups, total=len(backups))

        except Exception as e:
            logger.error(f"[ConfigService] Failed to list backups: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to list backups: {str(e)}"
            ) from e

    async def restore_backup(self, filename: str, user: str) -> ConfigUpdateResponse:
        """
        Restore from backup.

        Args:
            filename: Backup filename
            user: User performing restore

        Returns:
            ConfigUpdateResponse with operation result
        """
        try:
            backup_dir = self.yaml_manager.backup_dir
            backup_path = backup_dir / filename

            if not backup_path.exists():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Backup file '{filename}' not found")

            self.yaml_manager.restore_backup(backup_path, "modbus_device")

            config = self.yaml_manager.read_config("modbus_device")

            logger.info(f"[ConfigService] Restored from backup '{filename}' by {user}")

            return ConfigUpdateResponse(
                status=ResponseStatus.SUCCESS,
                message=f"Configuration restored from backup '{filename}'",
                generation=config.metadata.generation,
                checksum=config.metadata.checksum,
                modified_at=config.metadata.last_modified,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[ConfigService] Failed to restore backup: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to restore backup: {str(e)}"
            ) from e

    # ============================================================================
    # Helper Methods
    # ============================================================================

    @staticmethod
    def _find_device_index(devices: list, model: str, slave_id: int) -> int | None:
        """Find device index by model and slave_id"""
        for i, device in enumerate(devices):
            if device.model == model and device.slave_id == slave_id:
                return i
        return None
