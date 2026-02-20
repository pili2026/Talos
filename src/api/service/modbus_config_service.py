"""
Configuration Management Service
Business logic for modbus device configuration with version control
"""

import logging

from fastapi import HTTPException, status

from api.model.common import ConfigUpdateResponse, MetadataResponse
from api.model.enums import ResponseStatus
from api.model.modbus_config import (
    MetadataInfo,
    ModbusBusCreateRequest,
    ModbusBusInfo,
    ModbusConfigResponse,
    ModbusDeviceCreateRequest,
    ModbusDeviceInfo,
)
from api.service.base_config_service import BaseConfigService
from core.schema.config_metadata import ConfigSource
from core.schema.modbus_device_schema import ModbusBusConfig, ModbusDeviceConfig
from core.util.config_manager import ConfigManager
from core.util.yaml_manager import YAMLManager

logger = logging.getLogger(__name__)


class ConfigService(BaseConfigService):
    """
    Configuration Management Service for modbus devices.
    Inherits backup operations from BaseConfigService.
    """

    def __init__(self, yaml_manager: YAMLManager, config_manager: ConfigManager | None = None):
        super().__init__(yaml_manager=yaml_manager, config_type="modbus_device")
        self.config_manager = config_manager

    # ============================================================================
    # Metadata Operations
    # ============================================================================

    async def get_metadata(self) -> MetadataResponse:
        try:
            metadata = self._yaml_manager.get_metadata("modbus_device")

            metadata_info = MetadataInfo(
                generation=metadata.generation,
                source=metadata.config_source.value,
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
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve metadata: {str(e)}",
            ) from e

    # ============================================================================
    # Configuration Operations
    # ============================================================================

    async def get_config(self) -> ModbusConfigResponse:
        try:
            config = self._yaml_manager.read_config("modbus_device")

            metadata_info = MetadataInfo(
                generation=config.metadata.generation,
                source=config.metadata.config_source.value,
                last_modified=config.metadata.last_modified,
                last_modified_by=config.metadata.last_modified_by,
                checksum=config.metadata.checksum,
                applied_at=config.metadata.applied_at,
                cloud_sync_id=config.metadata.cloud_sync_id,
            )

            buses = {
                name: ModbusBusInfo(name=name, port=bus.port, baudrate=bus.baudrate, timeout=bus.timeout)
                for name, bus in config.bus_dict.items()
            }

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
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve configuration: {str(e)}",
            ) from e

    # ============================================================================
    # Bus Operations
    # ============================================================================

    async def create_or_update_bus(
        self, bus_name: str, bus_request: ModbusBusCreateRequest, user: str
    ) -> ConfigUpdateResponse:
        try:
            config = self._yaml_manager.read_config("modbus_device")

            config.bus_dict[bus_name] = ModbusBusConfig(
                port=bus_request.port, baudrate=bus_request.baudrate, timeout=bus_request.timeout
            )

            self._yaml_manager.update_config("modbus_device", config, config_source=ConfigSource.EDGE, modified_by=user)

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
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create/update bus: {str(e)}",
            ) from e

    async def delete_bus(self, bus_name: str, user: str) -> ConfigUpdateResponse:
        try:
            config = self._yaml_manager.read_config("modbus_device")

            if bus_name not in config.bus_dict:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Bus '{bus_name}' not found")

            devices_using_bus = [f"{d.model}_{d.slave_id}" for d in config.device_list if d.bus == bus_name]
            if devices_using_bus:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Cannot delete bus '{bus_name}': in use by devices {devices_using_bus}",
                )

            del config.bus_dict[bus_name]

            self._yaml_manager.update_config("modbus_device", config, config_source=ConfigSource.EDGE, modified_by=user)

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
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete bus: {str(e)}",
            ) from e

    # ============================================================================
    # Device Operations
    # ============================================================================

    async def create_or_update_device(
        self, device_request: ModbusDeviceCreateRequest, user: str
    ) -> ConfigUpdateResponse:
        try:
            config = self._yaml_manager.read_config("modbus_device")

            if device_request.bus not in config.bus_dict:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Bus '{device_request.bus}' not found. Available: {list(config.bus_dict.keys())}",
                )

            new_device = ModbusDeviceConfig(
                model=device_request.model,
                type=device_request.type,
                model_file=device_request.model_file,
                slave_id=device_request.slave_id,
                bus=device_request.bus,
                modes=device_request.modes,
            )

            existing_index = self._find_device_index(config.device_list, device_request.model, device_request.slave_id)

            if existing_index is not None:
                config.device_list[existing_index] = new_device
                action = "updated"
            else:
                config.device_list.append(new_device)
                action = "created"

            self._yaml_manager.update_config("modbus_device", config, config_source=ConfigSource.EDGE, modified_by=user)

            logger.info(f"[ConfigService] Device {device_request.model}_{device_request.slave_id} {action} by {user}")

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
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create/update device: {str(e)}",
            ) from e

    async def delete_device(self, model: str, slave_id: int, user: str) -> ConfigUpdateResponse:
        try:
            config = self._yaml_manager.read_config("modbus_device")

            device_index = self._find_device_index(config.device_list, model, slave_id)
            if device_index is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail=f"Device {model}_{slave_id} not found"
                )

            config.device_list.pop(device_index)

            self._yaml_manager.update_config("modbus_device", config, config_source=ConfigSource.EDGE, modified_by=user)

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
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete device: {str(e)}",
            ) from e

    # ============================================================================
    # Backup Operations（Override restore_backup，base support list_backups）
    # ============================================================================

    async def restore_backup(self, filename: str, user: str) -> ConfigUpdateResponse:
        try:
            self._do_restore(filename)

            config = self._yaml_manager.read_config("modbus_device")

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
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to restore backup: {str(e)}",
            ) from e

    # ============================================================================
    # Helper Methods
    # ============================================================================

    @staticmethod
    def _find_device_index(devices: list, model: str, slave_id: int) -> int | None:
        for i, device in enumerate(devices):
            if device.model == model and device.slave_id == slave_id:
                return i
        return None
