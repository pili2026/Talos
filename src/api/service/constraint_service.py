"""
Constraint Service Layer

Handles business logic related to device constraints:
- Reading device constraints from configuration
- Merging global defaults with device-specific constraints
- Providing constraint information for validation
"""

import logging
from typing import Any

from api.model.enums import ResponseStatus
from api.model.responses import ConstraintInfo, DeviceConstraintResponse
from api.repository.config_repository import ConfigRepository
from core.schema.constraint_schema import ConstraintConfigSchema

logger = logging.getLogger(__name__)


class ConstraintService:
    """
    Constraint Operation Service

    Responsibilities:
    - Load and merge constraint configurations
    - Provide constraint information for devices
    - Handle constraint validation logic
    """

    def __init__(self, constraint_schema: ConstraintConfigSchema, config_repo: ConfigRepository):
        self._constraint_schema = constraint_schema
        self._config_repo = config_repo

    async def get_device_constraints(self, device_id: str) -> DeviceConstraintResponse | None:
        """
        Get constraints for a specific device.

        Args:
            device_id: Device identifier (format: model_slaveId).

        Returns:
            DeviceConstraintResponse | None: Constraint information, or None if device not found.
        """
        try:
            # Parse device_id to extract model and slave_id
            parts = device_id.split("_")
            if len(parts) < 2:
                logger.warning(f"Invalid device_id format: {device_id}")
                return None

            model = "_".join(parts[:-1])
            slave_id = parts[-1]

            # Get device config to verify it exists
            device_config = self._config_repo.get_device_config(device_id)
            if not device_config:
                logger.warning(f"Device not found: {device_id}")
                return None

            # Get constraints from schema
            constraints_dict = self._get_merged_constraints(model, slave_id)

            # Convert to ConstraintInfo objects
            constraints = {
                param_name: ConstraintInfo(
                    parameter_name=param_name,
                    min=constraint.get("min"),
                    max=constraint.get("max"),
                )
                for param_name, constraint in constraints_dict.items()
            }

            # Check if device has custom instance-level constraints
            has_custom = self._has_custom_constraints(model, slave_id)

            return DeviceConstraintResponse(
                status=ResponseStatus.SUCCESS,
                device_id=device_id,
                model=model,
                slave_id=slave_id,
                constraints=constraints,
                has_custom_constraints=has_custom,
            )

        except Exception as e:
            logger.error(f"Error getting constraints for device {device_id}: {e}", exc_info=True)
            return None

    async def get_all_device_constraints(self) -> list[DeviceConstraintResponse]:
        """
        Get constraints for all configured devices.

        Returns:
            list[DeviceConstraintResponse]: List of constraint information for all devices.
        """
        result = []
        device_configs = self._config_repo.get_all_device_configs()

        for device_id in device_configs.keys():
            constraint_response = await self.get_device_constraints(device_id)
            if constraint_response:
                result.append(constraint_response)
        return result

    def _get_merged_constraints(self, model: str, slave_id: str) -> dict[str, dict[str, Any]]:
        """
        Merge constraints from global defaults, device defaults, and instance-specific config.

        Priority (highest to lowest):
        1. Instance-specific constraints
        2. Device model default constraints
        3. Global default constraints

        Args:
            model: Device model name.
            slave_id: Device slave ID.

        Returns:
            dict: Merged constraints dictionary.
        """
        merged = {}

        # 1. Start with global defaults
        if self._constraint_schema.global_defaults and self._constraint_schema.global_defaults.default_constraints:
            for param_name, constraint in self._constraint_schema.global_defaults.default_constraints.items():
                merged[param_name] = {"min": constraint.min, "max": constraint.max}

        # 2. Apply device model defaults
        device_config = self._constraint_schema.devices.get(model)
        if device_config and device_config.default_constraints:
            for param_name, constraint in device_config.default_constraints.items():
                merged[param_name] = {"min": constraint.min, "max": constraint.max}

        # 3. Apply instance-specific constraints (highest priority)
        if device_config and device_config.instances:
            instance_config = device_config.instances.get(slave_id)
            if instance_config and instance_config.constraints:
                for param_name, constraint in instance_config.constraints.items():
                    merged[param_name] = {"min": constraint.min, "max": constraint.max}

        return merged

    def _has_custom_constraints(self, model: str, slave_id: str) -> bool:
        """
        Check if a device has custom instance-level constraints.

        Args:
            model: Device model name.
            slave_id: Device slave ID.

        Returns:
            bool: True if device has custom constraints.
        """
        device_config = self._constraint_schema.devices.get(model)
        if not device_config or not device_config.instances:
            return False

        instance_config = device_config.instances.get(slave_id)
        return (
            instance_config is not None
            and instance_config.constraints is not None
            and len(instance_config.constraints) > 0
        )
