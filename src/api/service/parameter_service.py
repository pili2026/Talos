"""
Parameter Service Layer

Handles business logic for parameter read/write operations.
Integrates Modbus operations with constraint validation.
"""

import asyncio
import logging
from typing import Any

from api.model.enums import ParameterType
from api.model.responses import ParameterValue
from api.repository.config_repository import ConfigRepository
from api.repository.modbus_repository import ModbusRepository

logger = logging.getLogger(__name__)


class ParameterService:
    """
    Parameter Operation Service

    Responsibilities:
    - Read parameter values
    - Write parameter values
    - Validate constraint conditions
    - Value conversion (raw <-> actual)
    """

    def __init__(self, modbus_repo: ModbusRepository, config_repo: ConfigRepository):
        """
        Initialize the parameter service.

        Args:
            modbus_repo: Data access layer for Modbus operations.
            config_repo: Data access layer for configuration management.
        """
        self._modbus_repo = modbus_repo
        self._config_repo = config_repo

    async def read_parameter(self, device_id: str, parameter: str) -> ParameterValue:
        """
        Read a single parameter.

        Optimization:
        - Check device connection status if read fails.
        - Provide clearer error messages.
        """
        try:
            # Normalize parameter name
            normalized_param = self._config_repo._normalize_parameter_name(device_id, parameter)

            if not normalized_param:
                device_config = self._config_repo.get_device_config(device_id)
                available_params = device_config.get("available_parameters", []) if device_config else []

                return ParameterValue(
                    name=parameter,
                    value=0.0,
                    type=ParameterType.READ_ONLY,
                    is_valid=False,
                    error_message=f"Parameter '{parameter}' not found. Available: {', '.join(available_params[:5])}{'...' if len(available_params) > 5 else ''}",
                )

            param_def = self._config_repo.get_parameter_definition(device_id, normalized_param)

            if not param_def:
                return ParameterValue(
                    name=normalized_param,
                    value=0.0,
                    type=ParameterType.READ_ONLY,
                    is_valid=False,
                    error_message="Parameter definition not found",
                )

            # Get offset and register type
            register_offset = param_def.get("offset")

            if register_offset is None:
                return ParameterValue(
                    name=normalized_param,
                    value=0.0,
                    type=ParameterType.READ_ONLY,
                    is_valid=False,
                    error_message="Parameter has no offset defined",
                )

            register_type = param_def.get("type", "holding")
            if register_type not in ["holding", "input"]:
                logger.warning(f"Invalid register type '{register_type}' for {normalized_param}, using 'holding'")
                register_type = "holding"

            logger.info(f"[READ] Device: {device_id}, Parameter: {parameter} -> {normalized_param}")
            logger.info(
                f"[READ] Offset: {register_offset}, Type: {register_type}, Scale: {param_def.get('scale', 1.0)}"
            )

            # Check if a 32-bit register combination is needed
            combine_high_offset = param_def.get("combine_high")

            # Read raw value
            raw_value = await self._modbus_repo.read_register(
                device_id=device_id,
                register_offset=register_offset,
                register_type=register_type,
                combine_high_offset=combine_high_offset,
            )

            logger.info(f"[READ] Raw value from Modbus: {raw_value}")

            if raw_value is None:
                #  Read failed, check device status
                device_status = self._modbus_repo.get_device_status(device_id)
                failure_count = device_status.get("failure_count", 0)

                error_message = "Failed to read from Modbus"

                # If failed multiple times consecutively, device may be offline
                if failure_count >= 2:
                    logger.warning(f"[READ] Device {device_id} may be offline (failure_count={failure_count})")

                    # Quick connection test
                    is_online = await self._modbus_repo.test_connection(device_id, use_cache=False)

                    if not is_online:
                        error_message = "Device is offline or not responding"
                        logger.error(f"[READ] Confirmed: {device_id} is offline")

                return ParameterValue(
                    name=normalized_param,
                    value=0.0,
                    type=self._get_parameter_type(param_def),
                    is_valid=False,
                    error_message=error_message,
                )

            # Convert to actual value
            actual_value = self._convert_raw_to_actual(raw_value, param_def)

            logger.info(f"[READ] Actual value after conversion: {actual_value}")

            return ParameterValue(
                name=normalized_param,
                value=actual_value,
                unit=param_def.get("unit"),
                type=self._get_parameter_type(param_def),
                is_valid=True,
            )

        except Exception as e:
            logger.error(f"Error reading parameter {parameter} from {device_id}: {e}", exc_info=True)
            return ParameterValue(
                name=parameter, value=0.0, type=ParameterType.READ_ONLY, is_valid=False, error_message=str(e)
            )

    async def write_parameter(
        self, device_id: str, parameter: str, value: float, force: bool = False
    ) -> dict[str, Any]:
        """Write a parameter value."""
        try:
            # Normalize parameter name
            normalized_param = self._config_repo._normalize_parameter_name(device_id, parameter)

            if not normalized_param:
                return {"success": False, "error": f"Parameter '{parameter}' not found"}

            logger.info(f"[WRITE] Device: {device_id}, Parameter: {parameter} -> {normalized_param}, Value: {value}")

            param_def = self._config_repo.get_parameter_definition(device_id, normalized_param)
            if not param_def:
                return {"success": False, "error": f"Parameter '{normalized_param}' not found"}

            # Check if writable
            if not param_def.get("writable", False):
                return {"success": False, "error": f"Parameter '{normalized_param}' is read-only"}

            # Read current value
            current_param = await self.read_parameter(device_id, normalized_param)
            previous_value = current_param.value if current_param.is_valid else None

            logger.info(f"[WRITE] Previous value: {previous_value}")

            # Validate constraints
            if not force:
                if "bit" in param_def:
                    if value not in [0, 1, 0.0, 1.0]:
                        return {
                            "success": False,
                            "error": f"Bit value must be 0 or 1, got {value}",
                            "previous_value": previous_value,
                        }
                else:
                    constraint_check = self._check_constraints(device_id, normalized_param, value)
                    if not constraint_check["valid"]:
                        return {"success": False, "error": constraint_check["error"], "previous_value": previous_value}

            register_offset = param_def.get("offset")
            register_type = param_def.get("type", "holding")

            #  Handle Bit writing (atomic operation)
            if "bit" in param_def:
                bit_position = param_def.get("bit")
                bit_value = 1 if value != 0 else 0

                logger.info(f"[WRITE BIT] Using atomic bit operation: bit={bit_position}, value={bit_value}")

                #  Use atomic read-modify-write bit method
                write_success = await self._modbus_repo.read_modify_write_bit(
                    device_id=device_id,
                    register_offset=register_offset,
                    bit_position=bit_position,
                    bit_value=bit_value,
                    register_type=register_type,
                )
            else:
                # Standard write (non-bit mode)
                raw_value = self._convert_actual_to_raw(value, param_def)

                logger.info(f"[WRITE] Converting: actual={value} -> raw={raw_value}")

                write_success = await self._modbus_repo.write_register(
                    device_id=device_id, register_offset=register_offset, value=raw_value, register_type=register_type
                )

            if not write_success:
                return {"success": False, "error": "Modbus write failed", "previous_value": previous_value}

            # Verify write
            await asyncio.sleep(0.2)
            verify_param = await self.read_parameter(device_id, normalized_param)

            if not verify_param.is_valid:
                logger.warning(f"[WRITE] Verification read failed: {verify_param.error_message}")
                return {
                    "success": True,
                    "parameter": normalized_param,
                    "previous_value": previous_value,
                    "new_value": None,
                    "was_forced": force,
                    "warning": "Write completed but verification read failed",
                }

            logger.info(f"[WRITE] Verification: read back value = {verify_param.value}")

            # Check if write succeeded
            expected_value = 1.0 if value != 0 else 0.0
            if "bit" in param_def:
                if verify_param.value != expected_value:
                    logger.error(f"[WRITE] Verification failed: expected {expected_value}, got {verify_param.value}")
                    return {
                        "success": False,
                        "error": f"Write verification failed: expected {expected_value}, got {verify_param.value}",
                        "parameter": normalized_param,
                        "previous_value": previous_value,
                        "new_value": verify_param.value,
                        "was_forced": force,
                    }

            return {
                "success": True,
                "parameter": normalized_param,
                "previous_value": previous_value,
                "new_value": verify_param.value,
                "was_forced": force,
            }

        except Exception as e:
            logger.error(f"Error writing parameter {parameter} to {device_id}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def read_multiple_parameters(self, device_id: str, parameters: list[str]) -> list[ParameterValue]:
        """
        Read multiple parameters.

        Args:
            device_id: Device identifier.
            parameters: List of parameter names.

        Returns:
            list[ParameterValue]: List of parameter values.
        """
        results = []
        for param in parameters:
            param_value = await self.read_parameter(device_id, param)
            results.append(param_value)
        return results

    def _check_constraints(self, device_id: str, parameter: str, value: float) -> dict[str, Any]:
        """
        Validate parameter constraints.

        Args:
            device_id: Device identifier.
            parameter: Parameter name.
            value: Value to check.

        Returns:
            dict: Validation result.
        """
        constraints = self._config_repo.get_parameter_constraints(device_id, parameter)

        if not constraints:
            return {"valid": True}

        min_val = constraints.get("min")
        max_val = constraints.get("max")

        if min_val is not None and value < min_val:
            return {"valid": False, "error": f"Value {value} is below minimum constraint {min_val}"}

        if max_val is not None and value > max_val:
            return {"valid": False, "error": f"Value {value} exceeds maximum constraint {max_val}"}

        return {"valid": True}

    def _convert_raw_to_actual(self, raw_value: int, param_def: dict[str, Any]) -> float:
        """
        Convert a raw Modbus value to an actual value.

        Supports:
        - Standard conversion: actual = (raw * scale) + offset_value
        - Bit extraction: extract a specific bit from the register.

        Args:
            raw_value: Raw Modbus value.
            param_def: Parameter definition.

        Returns:
            float: Actual converted value.
        """
        #  Handle bit extraction (for DIO modules)
        if "bit" in param_def:
            bit_position = param_def.get("bit")

            # Extract the specified bit from raw_value
            bit_value = (raw_value >> bit_position) & 1

            logger.debug(f"[CONVERT BIT] raw={raw_value}, bit={bit_position}, value={bit_value}")

            return float(bit_value)  # Return 0.0 or 1.0

        #  Handle 32-bit combined registers
        if "combine_high" in param_def and "combine_scale" in param_def:
            scale = param_def.get("combine_scale", 1.0)
        else:
            scale = param_def.get("scale", 1.0)

        offset_value = param_def.get("offset_value", 0.0)

        result = (raw_value * scale) + offset_value

        #  Optional: round to reasonable precision
        precision = param_def.get("precision")

        if precision is None:
            # Auto-determine precision
            if scale >= 1:
                precision = 2
            elif scale >= 0.1:
                precision = 2
            elif scale >= 0.01:
                precision = 2
            elif scale >= 0.001:
                precision = 3
            else:
                precision = 4

        if precision is not None:
            result = round(result, precision)

        logger.debug(
            f"[CONVERT] raw={raw_value}, scale={scale}, offset={offset_value}, result={result}, precision={precision}"
        )

        return result

    def _convert_actual_to_raw(self, actual_value: float, param_def: dict[str, Any]) -> int:
        """
        Convert an actual value back to a raw Modbus value (for writing).

        Supports:
        - Standard conversion: raw = (actual - offset_value) / scale
        - Bit setting: requires reading the existing register value,
          modifying the bit, and writing back.

        Args:
            actual_value: Actual value to convert.
            param_def: Parameter definition.

        Returns:
            int: Raw Modbus value.
        """
        #  Handle bit writes (for DIO modules)
        # Note: bit writes require read-modify-write handling
        if "bit" in param_def:
            bit_position = param_def.get("bit")

            # Ensure value is 0 or 1
            bit_value = 1 if actual_value != 0 else 0

            logger.debug(f"[CONVERT BIT] actual={actual_value}, bit={bit_position}, bit_value={bit_value}")

            #  Note: Only return bit_value here
            # Actual writing logic is handled in write_parameter
            return bit_value

        #  Handle 32-bit combined registers
        if "combine_high" in param_def and "combine_scale" in param_def:
            scale = param_def.get("combine_scale", 1.0)
        else:
            scale = param_def.get("scale", 1.0)

        offset_value = param_def.get("offset_value", 0.0)

        # Prevent division by zero
        if scale == 0:
            logger.error("[CONVERT] Scale is 0, cannot convert")
            return 0

        raw_value = (actual_value - offset_value) / scale

        logger.debug(
            f"[CONVERT actual->raw] actual={actual_value}, scale={scale}, offset={offset_value}, raw={raw_value}"
        )

        return int(round(raw_value))

    def _get_parameter_type(self, param_def: dict[str, Any]) -> ParameterType:
        """
        Determine the parameter type.

        Args:
            param_def: Parameter definition.

        Returns:
            ParameterType: Enum representing the parameter type.
        """
        if param_def.get("writable", False):
            return ParameterType.READ_WRITE
        else:
            return ParameterType.READ_ONLY
