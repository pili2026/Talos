"""
Application Lifecycle Management

Handles FastAPI startup and shutdown events.
Initializes and cleans up shared resources.
"""

import logging
from api.repository.modbus_repository import ModbusRepository
from api.repository.config_repository import ConfigRepository

logger = logging.getLogger(__name__)


async def startup_event():
    """
    Application startup event

    Initialization steps:
    - Load configuration files
    - Create Modbus connection pool
    - Verify device availability
    """
    logger.info("Starting Talos API Service...")

    try:
        # Initialize configuration (Note: using synchronous method)
        config_repo = ConfigRepository()
        config_repo.initialize_sync()
        logger.info("Configuration loaded successfully")

        # Initialize Modbus connections
        modbus_repo = ModbusRepository()
        await modbus_repo.initialize()
        logger.info("Modbus connections initialized")

        logger.info("Talos API Service started successfully")
    except Exception as e:
        logger.error(f"Failed to start API service: {e}")
        raise


async def shutdown_event():
    """
    Application shutdown event

    Cleanup steps:
    - Close Modbus connections
    - Release resources
    """
    logger.info("Shutting down Talos API Service...")

    try:
        # Close Modbus connections
        modbus_repo = ModbusRepository()
        await modbus_repo.cleanup()
        logger.info("Modbus connections closed")

        logger.info("Talos API Service stopped successfully")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
