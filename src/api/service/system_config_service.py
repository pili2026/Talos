"""
System Config Service
Business logic for system_config.yml with version control
"""

import logging

from fastapi import HTTPException, status

from api.model.enums import ResponseStatus
from api.model.system_config import (
    SystemConfigInfo,
    SystemConfigResponse,
    SystemConfigUpdateRequest,
    SystemConfigUpdateResponse,
)
from core.schema.config_metadata import ConfigSource
from core.schema.system_config_schema import SystemConfig, SystemConfigFileSchema
from core.util.yaml_manager import YAMLManager

logger = logging.getLogger(__name__)


class SystemConfigService:
    """
    System config management service.
    """

    def __init__(self, yaml_manager: YAMLManager, system_config: SystemConfig):
        self._yaml_manager = yaml_manager
        self._system_config = system_config

    # ============================================================================
    # Private Helpers
    # ============================================================================

    def _read_schema(self) -> SystemConfigFileSchema:
        return self._yaml_manager.read_config("system_config")

    def _write_schema(self, schema: SystemConfigFileSchema) -> None:
        self._yaml_manager.update_config(
            "system_config",
            schema,
            config_source=ConfigSource.EDGE,
        )

    # ============================================================================
    # Config Operations
    # ============================================================================

    def get_config(self) -> SystemConfigResponse:
        return SystemConfigResponse(
            status=ResponseStatus.SUCCESS,
            config=SystemConfigInfo(
                monitor_interval_seconds=self._system_config.MONITOR_INTERVAL_SECONDS,
                control_interval_seconds=self._system_config.CONTROL_INTERVAL_SECONDS,
                alert_interval_seconds=self._system_config.ALERT_INTERVAL_SECONDS,
                device_id_series=self._system_config.DEVICE_ID_POLICY.SERIES,
                reverse_ssh_port=self._system_config.REMOTE_ACCESS.REVERSE_SSH.PORT or 8600,
                reverse_ssh_port_source="config",
            ),
        )

    def update_config(self, req: SystemConfigUpdateRequest) -> SystemConfigUpdateResponse:
        try:
            schema = self._read_schema()

            schema.MONITOR_INTERVAL_SECONDS = req.monitor_interval_seconds
            schema.DEVICE_ID_POLICY.SERIES = req.device_id_series

            schema.CONTROL_INTERVAL_SECONDS = req.control_interval_seconds
            schema.ALERT_INTERVAL_SECONDS = req.alert_interval_seconds

            self._write_schema(schema)

            # Synchronous update in-memory
            self._system_config.MONITOR_INTERVAL_SECONDS = req.monitor_interval_seconds
            self._system_config.DEVICE_ID_POLICY.SERIES = req.device_id_series

            logger.info(
                f"[SystemConfigService] Updated: "
                f"interval={req.monitor_interval_seconds}, control_interval={req.control_interval_seconds}, "
                f"alert_interval={req.alert_interval_seconds}, series={req.device_id_series}"
            )

            return SystemConfigUpdateResponse(
                status=ResponseStatus.SUCCESS,
                message="System config updated. Restart Talos service to apply changes.",
            )

        except Exception as e:
            logger.error(f"[SystemConfigService] Failed to update config: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update system config: {str(e)}",
            ) from e

    def update_reverse_ssh_port(self, port: int) -> None:
        """Called by ProvisionService via callback after updating connectserver.service."""
        try:
            schema = self._read_schema()
            schema.REMOTE_ACCESS.REVERSE_SSH.PORT = port

            self._write_schema(schema)

            # Synchronous update in-memory
            self._system_config.REMOTE_ACCESS.REVERSE_SSH.PORT = port

            logger.info(f"[SystemConfigService] REMOTE_ACCESS.REVERSE_SSH.PORT synced to {port}")

        except Exception as e:
            logger.warning(f"[SystemConfigService] Failed to sync SSH port to yml: {e}")
