"""
Instance Config Service
Handles read/write operations for device_instance_config.yml
"""

import logging
from typing import Any

from api.model.enum.config_type import ConfigTypeEnum
from api.model.instance_config import (
    ConstraintConfigRequest,
    DeviceConfigRequest,
    InstanceConfigRequest,
    InstanceConfigResponse,
    PinConfig,
    UpdateDeviceConfigRequest,
)
from core.schema.config_metadata import ConfigSource
from core.schema.constraint_schema import (
    ConstraintConfig,
    ConstraintConfigSchema,
    DeviceConfig,
    InitializationConfig,
    InstanceConfig,
)
from core.util.yaml_manager import YAMLManager

logger = logging.getLogger(__name__)


class InstanceConfigService:
    def __init__(self, yaml_manager: YAMLManager) -> None:
        self._yaml_manager = yaml_manager

    # =========================================================================
    # Read
    # =========================================================================

    def get_config(self) -> InstanceConfigResponse:
        """Read and return the full instance config, merged with modbus device list."""
        schema: ConstraintConfigSchema = self._read_schema()
        modbus_model_list: list[str] = self._get_modbus_models()
        return self._to_response(schema, modbus_model_list)

    def get_device_config(self, model: str) -> DeviceConfigRequest:
        """Read config for a specific device model."""
        schema = self._read_schema()
        device = schema.devices.get(model)
        if device is None:
            raise KeyError(f"Model '{model}' not found in instance config")
        return self._device_to_request(device)

    # =========================================================================
    # Write
    # =========================================================================

    def update_device_config(
        self,
        model: str,
        request: UpdateDeviceConfigRequest,
        modified_by: str = "web-user",
    ) -> InstanceConfigResponse:
        """Update config for a specific device model."""
        schema = self._read_schema()

        # Merge into existing schema
        schema.devices[model] = self._request_to_device(request.config)

        self._write_schema(schema, modified_by)
        logger.info(f"[InstanceConfigService] Updated device config for model='{model}'")
        return self._to_response(self._read_schema(), self._get_modbus_models())

    def update_instance(
        self,
        model: str,
        slave_id: str,
        request: InstanceConfigRequest,
        modified_by: str = "web-user",
    ) -> InstanceConfigResponse:
        """Update config for a specific device instance (model + slave_id)."""
        schema = self._read_schema()

        # Ensure device entry exists
        if model not in schema.devices:
            schema.devices[model] = DeviceConfig()

        device = schema.devices[model]
        if device.instances is None:
            device.instances = {}

        device.instances[slave_id] = self._request_to_instance(request)

        self._write_schema(schema, modified_by)
        logger.info(f"[InstanceConfigService] Updated instance config for model='{model}' slave_id='{slave_id}'")
        return self._to_response(self._read_schema(), self._get_modbus_models())

    # =========================================================================
    # Private Helpers
    # =========================================================================

    def _read_schema(self) -> ConstraintConfigSchema:
        return self._yaml_manager.read_config(ConfigTypeEnum.DEVICE_INSTANCE)

    def _write_schema(self, schema: ConstraintConfigSchema, modified_by: str) -> None:
        self._yaml_manager.update_config(
            ConfigTypeEnum.DEVICE_INSTANCE,
            schema,
            config_source=ConfigSource.EDGE,
            modified_by=modified_by,
        )

    def _to_response(
        self, schema: ConstraintConfigSchema, modbus_model_list: list[str] | None = None
    ) -> InstanceConfigResponse:
        devices = {model: self._device_to_request(device) for model, device in schema.devices.items()}

        if modbus_model_list:
            for model in modbus_model_list:
                if model not in devices:
                    devices[model] = DeviceConfigRequest(
                        initialization=None,
                        default_constraints=None,
                        instances={},
                    )

        return InstanceConfigResponse(
            status="success",
            global_defaults=schema.global_defaults.model_dump() if schema.global_defaults else None,
            devices=devices,
            generation=schema.metadata.generation,
            checksum=schema.metadata.checksum or None,
            modified_at=schema.metadata.last_modified or None,
        )

    # -------------------------------------------------------------------------
    # Schema ↔ Request conversion
    # -------------------------------------------------------------------------

    def _device_to_request(self, device: DeviceConfig) -> DeviceConfigRequest:
        return DeviceConfigRequest(
            initialization=device.initialization.model_dump() if device.initialization else None,
            default_constraints=(
                {k: ConstraintConfigRequest(min=v.min, max=v.max) for k, v in device.default_constraints.items()}
                if device.default_constraints
                else None
            ),
            instances=(
                {slave_id: self._instance_to_request(inst) for slave_id, inst in device.instances.items()}
                if device.instances
                else {}
            ),
        )

    def _instance_to_request(self, instance: InstanceConfig) -> InstanceConfigRequest:
        pins: dict[str, PinConfig] | None = None
        if instance.pins:
            pins = {
                pin_name: PinConfig(
                    remark=pin_data.get("remark"),
                    formula=pin_data.get("formula"),
                )
                for pin_name, pin_data in instance.pins.items()
            }

        return InstanceConfigRequest(
            initialization=instance.initialization.model_dump() if instance.initialization else None,
            constraints=(
                {k: ConstraintConfigRequest(min=v.min, max=v.max) for k, v in instance.constraints.items()}
                if instance.constraints
                else None
            ),
            use_default_constraints=(
                instance.use_default_constraints if instance.use_default_constraints is not None else True
            ),
            pins=pins,
        )

    def _request_to_device(self, req: DeviceConfigRequest) -> DeviceConfig:
        return DeviceConfig(
            initialization=InitializationConfig(**req.initialization) if req.initialization else None,
            default_constraints=(
                {k: ConstraintConfig(min=v.min, max=v.max) for k, v in req.default_constraints.items()}
                if req.default_constraints
                else None
            ),
            instances=(
                {slave_id: self._request_to_instance(inst) for slave_id, inst in req.instances.items()}
                if req.instances
                else None
            ),
        )

    def _request_to_instance(self, req: InstanceConfigRequest) -> InstanceConfig:
        pins: dict[str, dict[str, Any]] | None = None
        if req.pins:
            pins = {
                pin_name: {k: v for k, v in pin_cfg.model_dump().items() if v is not None}
                for pin_name, pin_cfg in req.pins.items()
            }

        return InstanceConfig(
            initialization=InitializationConfig(**req.initialization) if req.initialization else None,
            constraints=(
                {k: ConstraintConfig(min=v.min, max=v.max) for k, v in req.constraints.items()}
                if req.constraints
                else None
            ),
            use_default_constraints=req.use_default_constraints,
            pins=pins,
        )

    def _get_modbus_models(self) -> list[str]:
        """Get all device models from modbus_device config."""
        try:
            modbus_schema = self._yaml_manager.read_config(ConfigTypeEnum.MODBUS_DEVICE)
            return [device.model for device in (modbus_schema.device_list or [])]
        except Exception as e:
            logger.warning(f"[InstanceConfigService] Could not read modbus config: {e}")
            return []
