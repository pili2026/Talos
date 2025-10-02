"""
Reboot Counter

Responsibility: Manage persistent storage of system reboot count
"""

import logging
from pathlib import Path

from util.system_info.path_selector import PathSelector


logger = logging.getLogger("RebootCounter")


class RebootCounter:
    """
    Reboot Counter

    Features:
    - Read reboot count
    - Increment reboot count
    - Reset reboot count
    - Persist to file
    """

    def __init__(self, counter_file: str | None = None):
        """
        Initialize reboot counter

        Args:
            counter_file: Custom file path (optional).
                If None, automatically select the best path.
        """
        if counter_file:
            self.counter_file = Path(counter_file)
            logger.info(f"Using custom reboot counter: {self.counter_file}")
        else:
            state_dir = PathSelector.select_state_directory()
            self.counter_file = state_dir / "reboot_counter.txt"
            logger.info(f"Using reboot counter: {self.counter_file}")

        self._ensure_file()

    def _ensure_file(self):
        """
        Ensure counter file exists

        Raises:
            Exception: If file creation fails
        """
        try:
            # Ensure parent directory exists
            self.counter_file.parent.mkdir(parents=True, exist_ok=True)

            # If file does not exist, create it and initialize with 0
            if not self.counter_file.exists():
                self.counter_file.write_text("0")
                logger.info(f"Created reboot counter file: {self.counter_file}")
            else:
                logger.debug(f"Reboot counter file exists: {self.counter_file}")
        except PermissionError as e:
            logger.error(f"Permission denied: {self.counter_file}. Please check file permissions.")
            raise
        except Exception as e:
            logger.error(f"Failed to create reboot counter file: {e}")
            raise

    def get_count(self) -> int:
        """
        Get reboot count

        Returns:
            int: Reboot count, 0 if failed
        """
        try:
            if self.counter_file.exists():
                count_str = self.counter_file.read_text().strip()
                count = int(count_str)
                logger.debug(f"Current reboot count: {count}")
                return count
            else:
                logger.warning(f"Reboot counter file not found: {self.counter_file}")
                return 0
        except ValueError as e:
            logger.warning(f"Invalid count value in file, resetting to 0: {e}")
            self.reset()
            return 0
        except Exception as e:
            logger.warning(f"Failed to read reboot count: {e}")
            return 0

    def increment(self):
        """
        Increment reboot count

        Should be called during system startup
        """
        try:
            current = self.get_count()
            new_count = current + 1
            self.counter_file.write_text(str(new_count))
            logger.info(f"Reboot count incremented: {current} → {new_count}")
        except Exception as e:
            logger.error(f"Failed to increment reboot count: {e}")
            # Do not raise exception to avoid blocking program startup

    def reset(self):
        """
        Reset reboot count to 0

        Useful for maintenance or testing
        """
        try:
            self.counter_file.write_text("0")
            logger.info("Reboot count reset to 0")
        except Exception as e:
            logger.error(f"Failed to reset reboot count: {e}")

    def __repr__(self) -> str:
        return f"RebootCounter(file={self.counter_file}, count={self.get_count()})"
