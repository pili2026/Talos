"""
Parameter parsing utilities for WebSocket monitoring.

Handles parameter list parsing and validation,
following Talos configuration patterns.
"""

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class ConfigRepositoryProtocol(Protocol):
    """Protocol for configuration repository dependency."""

    def get_device_config(self, device_id: str) -> dict | None:
        """Get device configuration."""
        ...


class ParameterParseError(ValueError):
    """Raised when parameter parsing fails."""

    def __init__(self, message: str, device_id: str | None = None):
        self.device_id = device_id
        super().__init__(message)


def parse_parameter_list(
    parameters: str | None,
    device_id: str,
    config_repo: ConfigRepositoryProtocol,
) -> list[str]:
    """
    Parse parameter list from query string or device configuration.

    Follows Talos pattern: If parameters not specified, use all available
    parameters from device configuration.

    Args:
        parameters: Comma-separated parameter names (optional)
        device_id: Device identifier
        config_repo: Configuration repository for device lookup

    Returns:
        List of parameter names to monitor

    Raises:
        ParameterParseError: If device not found or no parameters available

    Example:
        >>> params = parse_parameter_list("temp,pressure", "SENSOR_01", config_repo)
        ['temp', 'pressure']

        >>> params = parse_parameter_list(None, "SENSOR_01", config_repo)
        ['temp', 'pressure', 'humidity']  # All available parameters
    """
    # If parameters specified, parse from string
    if parameters:
        param_list = [p.strip() for p in parameters.split(",") if p.strip()]
        logger.debug(f"[{device_id}] Using specified parameters: {param_list}")
        return param_list

    # Otherwise, get from device configuration
    device_config = config_repo.get_device_config(device_id)
    if not device_config:
        raise ParameterParseError(f"Device '{device_id}' not found in configuration", device_id=device_id)

    param_list = device_config.get("available_parameters", [])
    if not param_list:
        raise ParameterParseError(f"No parameters available for device {device_id}", device_id=device_id)

    logger.debug(f"[{device_id}] Using all available parameters: {param_list}")
    return param_list


def parse_device_list(device_ids: str) -> list[str]:
    """
    Parse device ID list from comma-separated string.

    Args:
        device_ids: Comma-separated device IDs

    Returns:
        List of device IDs

    Raises:
        ParameterParseError: If no devices specified

    Example:
        >>> devices = parse_device_list("VFD_01,VFD_02,VFD_03")
        ['VFD_01', 'VFD_02', 'VFD_03']
    """
    device_list = [d.strip() for d in device_ids.split(",") if d.strip()]

    if not device_list:
        raise ParameterParseError("No devices specified")

    logger.debug(f"Parsed device list: {device_list}")
    return device_list


def validate_parameter_names(
    parameters: list[str], available_parameters: list[str], device_id: str
) -> tuple[list[str], list[str]]:
    """
    Validate that requested parameters are available for the device.

    Args:
        parameters: Requested parameter names
        available_parameters: Parameters available for the device
        device_id: Device identifier (for logging)

    Returns:
        Tuple of (valid_parameters, invalid_parameters)

    Example:
        >>> valid, invalid = validate_parameter_names(
        ...     ["temp", "invalid", "pressure"],
        ...     ["temp", "pressure", "humidity"],
        ...     "SENSOR_01"
        ... )
        >>> valid
        ['temp', 'pressure']
        >>> invalid
        ['invalid']
    """
    available_set = set(available_parameters)
    valid_params = [p for p in parameters if p in available_set]
    invalid_params = [p for p in parameters if p not in available_set]

    if invalid_params:
        logger.warning(
            f"[{device_id}] Invalid parameters requested: {invalid_params}. " f"Available: {available_parameters}"
        )

    return valid_params, invalid_params


class ParameterListBuilder:
    """
    Builder for constructing parameter lists with validation.

    Provides a fluent interface for parameter list construction.

    Example:
        >>> builder = ParameterListBuilder(config_repo)
        >>> params = (builder
        ...     .for_device("SENSOR_01")
        ...     .from_query_string("temp,pressure")
        ...     .validate()
        ...     .build())
    """

    def __init__(self, config_repo: ConfigRepositoryProtocol):
        self.config_repo = config_repo
        self._device_id: str | None = None
        self._query_string: str | None = None
        self._should_validate: bool = False

    def for_device(self, device_id: str) -> "ParameterListBuilder":
        """Set the device ID."""
        self._device_id = device_id
        return self

    def from_query_string(self, parameters: str | None) -> "ParameterListBuilder":
        """Set parameters from query string."""
        self._query_string = parameters
        return self

    def validate(self) -> "ParameterListBuilder":
        """Enable validation against available parameters."""
        self._should_validate = True
        return self

    def build(self) -> list[str]:
        """
        Build and return the parameter list.

        Raises:
            ValueError: If device_id not set
            ParameterParseError: If parsing fails
        """
        if not self._device_id:
            raise ValueError("Device ID must be set before building")

        # Parse parameter list
        param_list = parse_parameter_list(self._query_string, self._device_id, self.config_repo)

        # Optionally validate
        if self._should_validate:
            device_config = self.config_repo.get_device_config(self._device_id)
            if device_config:
                available = device_config.get("available_parameters", [])
                valid_params, invalid_params = validate_parameter_names(param_list, available, self._device_id)

                if invalid_params:
                    logger.warning(f"[{self._device_id}] Removing invalid parameters: {invalid_params}")
                    param_list = valid_params

        return param_list


def parse_multi_device_parameters(
    device_ids: list[str],
    parameters: str | None,
    config_repo: ConfigRepositoryProtocol,
) -> dict[str, list[str]]:
    """
    Parse parameters for multiple devices.

    If parameters specified, use same list for all devices.
    Otherwise, use each device's available parameters.

    Args:
        device_ids: List of device identifiers
        parameters: Comma-separated parameter names (optional)
        config_repo: Configuration repository

    Returns:
        Dict mapping device_id to list of parameters

    Example:
        >>> params = parse_multi_device_parameters(
        ...     ["VFD_01", "VFD_02"],
        ...     "frequency,current",
        ...     config_repo
        ... )
        {'VFD_01': ['frequency', 'current'], 'VFD_02': ['frequency', 'current']}
    """
    # If parameters specified, use for all devices
    if parameters:
        param_list = [p.strip() for p in parameters.split(",") if p.strip()]
        return {device_id: param_list for device_id in device_ids}

    # Otherwise, get each device's parameters
    device_params = {}
    for device_id in device_ids:
        try:
            params = parse_parameter_list(None, device_id, config_repo)
            device_params[device_id] = params
        except ParameterParseError as e:
            logger.warning(f"Failed to get parameters for {device_id}: {e}")
            device_params[device_id] = []

    return device_params
