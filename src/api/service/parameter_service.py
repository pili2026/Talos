"""Parameter service that reuses the AsyncDeviceManager managed by Talos core."""

import asyncio
import logging
from typing import Any

from api.model.enums import ParameterType
from api.model.responses import ParameterValue
from api.repository.config_repository import ConfigRepository
from device.generic.generic_device import AsyncGenericModbusDevice
from device_manager import AsyncDeviceManager
from model.device_constant import DEFAULT_MISSING_VALUE
from schema.constraint_schema import ConstraintConfig
from util.value_util import safe_float

logger = logging.getLogger(__name__)


class ParameterService:
    """High-level parameter operations backed by :class:`AsyncDeviceManager`."""

    def __init__(self, device_manager: AsyncDeviceManager, config_repo: ConfigRepository):
        self._device_manager = device_manager
        self._config_repo = config_repo
        self.logger = logging.getLogger(__name__)

    async def read_parameter(self, device_id: str, parameter: str) -> ParameterValue:
        """Read a single parameter via the shared device manager."""

        device = self._get_device(device_id)
        if not device:
            return ParameterValue(
                name=parameter,
                value=0.0,
                type=ParameterType.READ_ONLY,
                is_valid=False,
                error_message=f"Device '{device_id}' not found",
            )

        normalized_param = self._normalize_parameter_name(device_id, parameter)
        if not normalized_param:
            available = self._config_repo.get_device_config(device_id) or {}
            available_params = available.get("available_parameters", [])
            preview = ", ".join(available_params[:5])
            if len(available_params) > 5:
                preview += "..."
            return ParameterValue(
                name=parameter,
                value=0.0,
                type=ParameterType.READ_ONLY,
                is_valid=False,
                error_message=f"Parameter '{parameter}' not found. Available: {preview}" if preview else None,
            )

        try:
            value = await device.read_value(normalized_param)
        except Exception as exc:  # pragma: no cover - defensive logging
            self.logger.error(f"Error reading {normalized_param} from {device_id}: {exc}")
            return ParameterValue(
                name=normalized_param,
                value=0.0,
                type=self._resolve_parameter_type(device, normalized_param),
                is_valid=False,
                error_message=str(exc),
            )

        if value == DEFAULT_MISSING_VALUE:
            return ParameterValue(
                name=normalized_param,
                value=0.0,
                type=self._resolve_parameter_type(device, normalized_param),
                is_valid=False,
                error_message=f"Failed to read parameter '{normalized_param}'",
            )

        param_cfg = device.register_map.get(normalized_param, {})
        unit = param_cfg.get("unit") or param_cfg.get("units")

        return ParameterValue(
            name=normalized_param,
            value=float(value),
            unit=unit,
            type=self._resolve_parameter_type(device, normalized_param),
            is_valid=True,
        )

    async def read_multiple_parameters(self, device_id: str, parameters: list[str]) -> list[ParameterValue]:
        """Read a batch of parameters from the shared device manager."""

        device: AsyncGenericModbusDevice | None = self._get_device(device_id)
        if not device:
            return [
                ParameterValue(
                    name=param,
                    value=0.0,
                    type=ParameterType.READ_ONLY,
                    is_valid=False,
                    error_message=f"Device '{device_id}' not found",
                )
                for param in parameters
            ]

        normalized_names: dict[str, str | None] = {
            param: self._normalize_parameter_name(device_id, param) for param in parameters
        }

        try:
            snapshot = await device.read_all()
        except Exception as exc:  # pragma: no cover - defensive logging
            self.logger.error(f"Failed to read snapshot for {device_id}: {exc}")
            return [
                ParameterValue(
                    name=param,
                    value=0.0,
                    type=ParameterType.READ_ONLY,
                    is_valid=False,
                    error_message=str(exc),
                )
                for param in parameters
            ]

        results: list[ParameterValue] = []
        for original_name, normalized in normalized_names.items():
            if not normalized:
                results.append(
                    ParameterValue(
                        name=original_name,
                        value=0.0,
                        type=ParameterType.READ_ONLY,
                        is_valid=False,
                        error_message=f"Parameter '{original_name}' not found",
                    )
                )
                continue

            value: float | int = snapshot.get(normalized, DEFAULT_MISSING_VALUE)
            param_config: dict = device.register_map.get(normalized, {})

            if value == DEFAULT_MISSING_VALUE:
                results.append(
                    ParameterValue(
                        name=normalized,
                        value=0.0,
                        type=self._resolve_parameter_type(device, normalized),
                        is_valid=False,
                        error_message=f"Failed to read parameter '{normalized}'",
                    )
                )
                continue

            unit = param_config.get("unit") or param_config.get("units")
            results.append(
                ParameterValue(
                    name=normalized,
                    value=safe_float(value),
                    unit=unit,
                    type=self._resolve_parameter_type(device, normalized),
                    is_valid=True,
                )
            )

        return results

    async def write_parameter(self, device_id: str, parameter: str, value: Any, force: bool = False) -> dict:
        """Write a parameter value through the shared device manager."""

        device = self._get_device(device_id)
        if not device:
            return {"success": False, "error": f"Device '{device_id}' not found"}

        normalized_param = self._normalize_parameter_name(device_id, parameter)
        if not normalized_param:
            return {"success": False, "error": f"Parameter '{parameter}' not found"}

        param_cfg = device.register_map.get(normalized_param)
        if not param_cfg:
            return {"success": False, "error": f"Parameter '{normalized_param}' not defined"}

        if not self._is_writable(param_cfg):
            return {"success": False, "error": f"Parameter '{normalized_param}' is read-only"}

        previous_value = await self._safe_read(device, normalized_param)

        constraint = device.constraints.constraints.get(normalized_param)
        in_range = self._constraint_allows(constraint, float(value))
        if constraint and not in_range and not force:
            return {
                "success": False,
                "error": (
                    f"Value {value} outside of allowed range "
                    f"[{constraint.min if constraint.min is not None else '-inf'}, "
                    f"{constraint.max if constraint.max is not None else 'inf'}]"
                ),
                "previous_value": previous_value,
            }

        override_state: tuple[float | None, float | None] | None = None
        if constraint and not in_range and force:
            override_state = (constraint.min, constraint.max)
            constraint.min = min(value, constraint.min if constraint.min is not None else value)
            constraint.max = max(value, constraint.max if constraint.max is not None else value)

        try:
            await device.write_value(normalized_param, value)
        except Exception as exc:
            self.logger.error(f"Failed to write {normalized_param} on {device_id}: {exc}")
            if override_state:
                constraint.min, constraint.max = override_state
            return {"success": False, "error": str(exc), "previous_value": previous_value}
        finally:
            if override_state:
                constraint.min, constraint.max = override_state

        await asyncio.sleep(0.1)
        new_value = await self._safe_read(device, normalized_param)

        if new_value is None:
            return {
                "success": True,
                "parameter": normalized_param,
                "previous_value": previous_value,
                "new_value": None,
                "was_forced": force,
                "warning": "Write completed but verification read failed",
            }

        return {
            "success": True,
            "parameter": normalized_param,
            "previous_value": previous_value,
            "new_value": new_value,
            "was_forced": force,
        }

    async def fast_test_device_connection(
        self, device_id: str, test_param_count: int = 5, min_success_rate: float = 0.3
    ) -> tuple[bool, str | None, dict]:
        """
        Fast connection test using Core's optimized method.

        Args:
            device_id: Device identifier
            test_param_count: Number of parameters to test
            min_success_rate: Minimum success rate (0.0-1.0)

        Returns:
            (success, error_message, details)
        """
        return await self._device_manager.fast_test_device_connection(device_id, test_param_count, min_success_rate)

    def _get_device(self, device_id: str) -> AsyncGenericModbusDevice | None:
        try:
            model, slave = device_id.rsplit("_", 1)
        except ValueError:
            self.logger.error(f"Invalid device_id format '{device_id}'")
            return None

        device = self._device_manager.get_device_by_model_and_slave_id(model, slave)
        if not device:
            self.logger.warning(f"Device '{device_id}' not managed by AsyncDeviceManager")
        return device

    def _normalize_parameter_name(self, device_id: str, parameter: str) -> str | None:
        try:
            return self._config_repo._normalize_parameter_name(device_id, parameter)
        except Exception as exc:  # pragma: no cover - defensive logging
            self.logger.error(f"Failed to normalize parameter '{parameter}' for {device_id}: {exc}")
            return None

    def _resolve_parameter_type(self, device: AsyncGenericModbusDevice, parameter: str) -> ParameterType:
        param_cfg = device.register_map.get(parameter, {})
        return ParameterType.READ_WRITE if self._is_writable(param_cfg) else ParameterType.READ_ONLY

    @staticmethod
    def _constraint_allows(constraint: ConstraintConfig, value: float) -> bool:
        if constraint is None:
            return True
        min_val = constraint.min if constraint.min is not None else float("-inf")
        max_val = constraint.max if constraint.max is not None else float("inf")
        return min_val <= value <= max_val

    async def _safe_read(self, device: AsyncGenericModbusDevice, parameter: str) -> float | None:
        try:
            value = await device.read_value(parameter)
        except Exception as exc:  # pragma: no cover - defensive logging
            self.logger.error(f"Verification read failed for {parameter}: {exc}")
            return None

        if value == DEFAULT_MISSING_VALUE:
            return None

        return float(value)

    @staticmethod
    def _is_writable(param_cfg: dict[str, Any]) -> bool:
        if not param_cfg:
            return False
        if param_cfg.get("writable") is True:
            return True
        access = param_cfg.get("access")
        return isinstance(access, str) and access.upper() in {"RW", "W"}
