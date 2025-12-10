import logging

from core.schema.virtual_device_schema import VirtualDevicesConfigSchema
from core.util.config_manager import ConfigManager
from core.util.virtual_device_manager import VirtualDeviceManager
from device_manager import AsyncDeviceManager

logger = logging.getLogger("VirtualDeviceFactory")


def initialize_virtual_device_manager(
    config_path: str | None, device_manager: AsyncDeviceManager
) -> VirtualDeviceManager | None:
    """
    Initialize Virtual Device Manager from configuration file.

    Args:
        config_path: Path to virtual device configuration file (optional)
        device_manager: Initialized AsyncDeviceManager instance

    Returns:
        VirtualDeviceManager instance if successful, None otherwise

    Examples:
        >>> virtual_mgr = initialize_virtual_device_manager(
        ...     "res/virtual_device.yml",
        ...     async_device_manager
        ... )
    """
    if not config_path:
        logger.info("No virtual device configuration path specified, " "skipping virtual device initialization")
        return None

    try:
        logger.info(f"Loading virtual device configuration from: {config_path}")

        # Load and validate configuration
        config_raw: dict = ConfigManager.load_yaml_file(config_path)
        config = VirtualDevicesConfigSchema(**config_raw)

        # Check if there are any virtual devices defined
        if not config.virtual_devices:
            logger.info("No virtual devices defined in configuration")
            return None

        # Create manager
        virtual_device_manager = VirtualDeviceManager(config=config, device_manager=device_manager)

        # Check if any devices are enabled
        enabled_count: int = len(virtual_device_manager.enabled_devices)

        if enabled_count > 0:
            logger.info(f"Virtual device manager initialized with {enabled_count} " f"enabled virtual device(s)")
            return virtual_device_manager

        logger.info("No virtual devices enabled in configuration")
        return None

    except FileNotFoundError:
        logger.warning(f"Virtual device configuration file not found: {config_path}")
        logger.info("Continuing without virtual devices")
        return None

    except Exception as e:
        logger.error(f"Failed to load virtual device configuration: {e}", exc_info=True)
        logger.warning("Continuing without virtual devices")
        return None
