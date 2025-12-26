"""
Control Execution History Storage

Manages persistent storage of control rule execution timestamps using SQLite.
Ensures time_elapsed conditions work correctly across system restarts.
"""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class ControlExecutionStore:
    """Persistent storage for control rule execution history"""

    def __init__(self, db_path: str, timezone: str = "Asia/Taipei"):
        """
        Initialize the execution history store.

        Args:
            db_path: Path to SQLite database file
            timezone: Timezone for timestamp handling
        """
        self.db_path = Path(db_path)
        self.tz = ZoneInfo(timezone)
        self._init_database()

    def _init_database(self):
        """Create the execution history table if it doesn't exist"""
        try:
            # Ensure parent directory exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            with sqlite3.connect(self.db_path) as conn:
                # TODO: Move to sql migration system if schema evolves
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS control_execution_history (
                        rule_code TEXT PRIMARY KEY,
                        last_execution_time TEXT NOT NULL,
                        device_model TEXT NOT NULL,
                        device_slave_id TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                """
                )
                conn.commit()
                logger.info(f"[STORE] Initialized control execution history at {self.db_path}")

        except Exception as e:
            logger.error(f"[STORE] Failed to initialize database: {e}", exc_info=True)
            raise

    def get_last_execution(self, rule_code: str) -> datetime | None:
        """
        Get the last execution time for a rule.

        Args:
            rule_code: Unique rule code

        Returns:
            Last execution datetime (timezone-aware), or None if never executed
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT last_execution_time FROM control_execution_history WHERE rule_code = ?",
                    (rule_code,),
                )
                row = cursor.fetchone()

                if row:
                    # Parse ISO format and ensure timezone-aware
                    dt = datetime.fromisoformat(row[0])
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=self.tz)
                    logger.debug(f"[STORE] Retrieved last execution for '{rule_code}': {dt}")
                    return dt
                else:
                    logger.debug(f"[STORE] No execution history found for '{rule_code}'")
                    return None

        except Exception as e:
            logger.error(f"[STORE] Failed to get last execution for '{rule_code}': {e}", exc_info=True)
            return None

    def update_execution(self, rule_code: str, execution_time: datetime, device_model: str, device_slave_id: str):
        """
        Update the last execution time for a rule.

        Args:
            rule_code: Unique rule code
            execution_time: Execution timestamp (timezone-aware)
            device_model: Device model (for reference)
            device_slave_id: Device slave ID (for reference)
        """
        try:
            # Ensure timezone-aware
            if execution_time.tzinfo is None:
                execution_time = execution_time.replace(tzinfo=self.tz)

            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO control_execution_history 
                    (rule_code, last_execution_time, device_model, device_slave_id, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(rule_code) DO UPDATE SET
                        last_execution_time = excluded.last_execution_time,
                        updated_at = excluded.updated_at
                """,
                    (
                        rule_code,
                        execution_time.isoformat(),
                        device_model,
                        device_slave_id,
                        datetime.now(self.tz).isoformat(),
                    ),
                )
                conn.commit()
                logger.info(
                    f"[STORE] Updated execution for '{rule_code}': "
                    f"{device_model}_{device_slave_id} at {execution_time}"
                )

        except Exception as e:
            logger.error(f"[STORE] Failed to update execution for '{rule_code}': {e}", exc_info=True)

    def clear_history(self, rule_code: str | None = None):
        """
        Clear execution history.

        Args:
            rule_code: Specific rule to clear, or None to clear all
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                if rule_code:
                    conn.execute("DELETE FROM control_execution_history WHERE rule_code = ?", (rule_code,))
                    logger.info(f"[STORE] Cleared execution history for '{rule_code}'")
                else:
                    conn.execute("DELETE FROM control_execution_history")
                    logger.info("[STORE] Cleared all execution history")
                conn.commit()

        except Exception as e:
            logger.error(f"[STORE] Failed to clear history: {e}", exc_info=True)

    def get_all_executions(self) -> dict[str, dict]:
        """
        Get all execution records (for debugging/monitoring).

        Returns:
            Dict mapping rule_code to execution info
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    """
                    SELECT rule_code, last_execution_time, device_model, device_slave_id, updated_at
                    FROM control_execution_history
                    ORDER BY updated_at DESC
                """
                )
                rows = cursor.fetchall()

                result = {}
                for row in rows:
                    rule_code, last_exec, model, slave_id, updated = row
                    result[rule_code] = {
                        "last_execution_time": last_exec,
                        "device_model": model,
                        "device_slave_id": slave_id,
                        "updated_at": updated,
                    }

                return result

        except Exception as e:
            logger.error(f"[STORE] Failed to get all executions: {e}", exc_info=True)
            return {}
