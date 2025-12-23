"""
Logging Configuration
Centralized management of application log format and levels.
"""

import logging
import sys
from pathlib import Path


def setup_logging(log_level: str = "INFO", log_to_file: bool = True):
    """
    Configure application logging.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_to_file: Whether to write logs to file
    """
    # Create log directory
    log_dir = Path(__file__).parent.parent.parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)

    # Log format
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Build handlers
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_to_file:
        handlers.append(logging.FileHandler(log_dir / "api.log", encoding="utf-8"))

    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format=log_format,
        datefmt=date_format,
        handlers=handlers,
    )

    # Adjust third-party library logging levels (to reduce noise)
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("fastapi").setLevel(logging.INFO)

    # PyModbus: Suppress noisy logs during normal RS-485 communication
    # These are expected when devices are offline and don't indicate errors
    logging.getLogger("pymodbus").setLevel(logging.ERROR)
    logging.getLogger("pymodbus.client").setLevel(logging.ERROR)
    logging.getLogger("pymodbus.transaction").setLevel(logging.ERROR)
    logging.getLogger("pymodbus.factory").setLevel(logging.ERROR)

    # Suppress RS-485 noise warnings (these are normal with offline devices)
    logging.getLogger("pymodbus.logging").setLevel(logging.CRITICAL)
    logging.getLogger("pymodbus.rtunoise").setLevel(logging.CRITICAL)
