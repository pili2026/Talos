import logging
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


class ISO8601Formatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt: datetime = datetime.fromtimestamp(record.created)
        return dt.isoformat(timespec="seconds")


def setup_logging(
    log_level=logging.INFO,
    log_to_file: bool = False,
    log_dir: str = "logs",
    log_base_filename: str = "talos",
    when: str = "midnight",
    backup_count: int = 7,
):
    formatter = ISO8601Formatter(fmt="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    if not root_logger.handlers:
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        # File handler (rotating daily)
        if log_to_file:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            file_path = f"{log_dir}/{log_base_filename}.log"

            rotating_handler = TimedRotatingFileHandler(
                filename=file_path,
                when=when,  # 'midnight' → rotate at 00:00
                interval=1,
                backupCount=backup_count,
                encoding="utf-8",
                utc=False,
            )
            rotating_handler.setFormatter(formatter)
            root_logger.addHandler(rotating_handler)
