"""
Device Service Layer

Handles business logic related to devices:
- Querying device lists
- Checking device status
- Managing device information
"""

from typing import Any

from api.model.enums import DeviceConnectionStatus
from api.model.responses import DeviceInfo
from api.repository.config_repository import ConfigRepository
from device_manager import AsyncDeviceManager


class DeviceService:
    """
    Device Operation Service

    Responsibilities:
    - Manage device list
    - Query device status
    - Validate device existence
    """

    def __init__(self, device_manager: AsyncDeviceManager, config_repo: ConfigRepository):
        self._device_manager = device_manager
        self._config_repo = config_repo

    async def get_all_devices(self, include_status: bool = False) -> list[DeviceInfo]:
        """
        Retrieve a list of all devices.

        Args:
            include_status: Whether to check actual device connectivity.

        Returns:
            list[DeviceInfo]: List of device information.
        """
        device_configs: dict[str, dict[str, Any]] = self._config_repo.get_all_device_configs()
        devices = []

        for device_id, config in device_configs.items():
            device_info = await self._build_device_info(config, include_status=include_status)
            devices.append(device_info)

        return devices

    async def get_device_by_id(self, device_id: str, include_status: bool = True) -> DeviceInfo | None:
        """
        Retrieve device information by ID.

        Args:
            device_id: Unique device identifier.
            include_status: Whether to check actual device connectivity.

        Returns:
            DeviceInfo | None: Device information, or None if not found.
        """
        config = self._config_repo.get_device_config(device_id)
        if not config:
            return None

        return await self._build_device_info(config, include_status=include_status)

    async def check_device_connectivity(self, device_id: str) -> DeviceConnectionStatus:
        """
        Check the connection status of a device.

        Args:
            device_id: Device identifier.

        Returns:
            DeviceConnectionStatus: Connection status.
        """
        try:
            is_connected = await self._device_manager.test_device_connection(device_id)
            return DeviceConnectionStatus.ONLINE if is_connected else DeviceConnectionStatus.OFFLINE
        except Exception:
            return DeviceConnectionStatus.ERROR

    def get_all_device_models(self) -> list[dict[str, Any]]:
        """
        Retrieve all device models (from driver files).

        Returns:
            list[dict]: List of device models.
        """
        models = []

        # Get all models from the config repository
        all_models = self._config_repo.get_all_models()

        for model_name in all_models:
            model_def = self._config_repo.get_model_definition(model_name)
            if not model_def:
                continue

            register_map = model_def.get("register_map", {})

            models.append(
                {
                    "model": model_name,
                    "description": model_def.get("description", ""),
                    "manufacturer": model_def.get("manufacturer", ""),
                    "available_parameters": list(register_map.keys()),
                    "parameter_count": len(register_map),
                    "supports_read": any(reg.get("readable", True) for reg in register_map.values()),
                    "supports_write": any(reg.get("writable", False) for reg in register_map.values()),
                }
            )

        return models

    async def _build_device_info(self, config: dict[str, Any], include_status: bool = False) -> DeviceInfo:
        """
        Build a DeviceInfo object.

        Args:
            config: Device configuration dictionary.
            include_status: Whether to check actual device connectivity.

        Returns:
            DeviceInfo: Constructed device information object.
        """
        device_id = config["device_id"]

        if include_status:
            connection_status = await self.check_device_connectivity(device_id)
        else:
            connection_status = DeviceConnectionStatus.UNKNOWN

        return DeviceInfo(
            device_id=device_id,
            model=config["model"],
            slave_id=config["slave_id"],
            connection_status=connection_status.value,
            available_parameters=config.get("available_parameters", []),
        )
