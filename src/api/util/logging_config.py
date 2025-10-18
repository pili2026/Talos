"""
Logging Configuration

Centralized management of application log format and levels.
"""

import logging
import sys
from pathlib import Path


def setup_logging(log_level: str = "INFO"):
    """
    Configure application logging.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
    """
    # Create log directory
    log_dir = Path(__file__).parent.parent.parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)

    # Log format
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format=log_format,
        datefmt=date_format,
        handlers=[
            # Output to console
            logging.StreamHandler(sys.stdout),
            # Output to file
            logging.FileHandler(log_dir / "api.log", encoding="utf-8"),
        ],
    )

    # Adjust third-party library logging levels (to reduce noise)
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("fastapi").setLevel(logging.INFO)
    logging.getLogger("pymodbus").setLevel(logging.WARNING)
