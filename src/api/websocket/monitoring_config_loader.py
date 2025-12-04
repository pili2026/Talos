"""
Configuration loading utilities for WebSocket monitoring.

Provides functions to load MonitoringConfig from various sources,
following Talos configuration patterns.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from api.websocket.monitoring_config import MonitoringConfig


def load_monitoring_config_from_yaml(config_path: str | Path) -> MonitoringConfig:
    """
    Load MonitoringConfig from YAML file.

    Args:
        config_path: Path to YAML configuration file

    Returns:
        Validated MonitoringConfig instance

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValidationError: If config validation fails
        yaml.YAMLError: If YAML parsing fails

    Example:
        >>> config = load_monitoring_config_from_yaml("config/monitoring.yml")
        >>> config.max_consecutive_failures
        5
    """
    config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config_dict = yaml.safe_load(f)

    if not config_dict:
        raise ValueError(f"Empty configuration file: {config_path}")

    return MonitoringConfig(**config_dict)


def load_monitoring_config_from_dict(config_dict: dict[str, Any]) -> MonitoringConfig:
    """
    Load MonitoringConfig from dictionary.

    Useful for loading from existing configuration structures.

    Args:
        config_dict: Configuration dictionary

    Returns:
        Validated MonitoringConfig instance

    Example:
        >>> config = load_monitoring_config_from_dict({
        ...     "max_consecutive_failures": 5,
        ...     "default_single_device_interval": 2.0
        ... })
    """
    return MonitoringConfig(**config_dict)


def create_default_config_file(output_path: str | Path) -> None:
    """
    Create a default monitoring configuration YAML file.

    Useful for first-time setup or generating templates.

    Args:
        output_path: Path where to save the configuration file

    Example:
        >>> create_default_config_file("config/monitoring_default.yml")
    """
    default_config = MonitoringConfig()
    config_dict = default_config.model_dump()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(config_dict, f, default_flow_style=False, sort_keys=False)


def validate_config_file(config_path: str | Path) -> tuple[bool, str]:
    """
    Validate a monitoring configuration file.

    Args:
        config_path: Path to configuration file

    Returns:
        Tuple of (is_valid, error_message)
        If valid, error_message is empty string

    Example:
        >>> is_valid, error = validate_config_file("config/monitoring.yml")
        >>> if not is_valid:
        ...     print(f"Configuration error: {error}")
    """
    try:
        load_monitoring_config_from_yaml(config_path)
        return True, ""
    except FileNotFoundError as e:
        return False, f"File not found: {e}"
    except ValidationError as e:
        return False, f"Validation error: {e}"
    except yaml.YAMLError as e:
        return False, f"YAML parsing error: {e}"
    except Exception as e:
        return False, f"Unexpected error: {e}"


# Example configuration structure for documentation
EXAMPLE_CONFIG_YAML = """
# WebSocket Monitoring Configuration
# This file configures the behavior of WebSocket monitoring endpoints

# Maximum consecutive failures before closing connection
max_consecutive_failures: 3

# Default update interval for single device monitoring (seconds)
default_single_device_interval: 1.0

# Default update interval for multi-device monitoring (seconds)
default_multi_device_interval: 2.0

# Minimum allowed update interval (seconds)
min_interval: 0.5

# Maximum allowed update interval (seconds)
max_interval: 60.0

# Whether to enable device control commands via WebSocket
enable_control_commands: true
"""
