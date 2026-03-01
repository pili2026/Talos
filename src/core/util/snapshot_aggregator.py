import json
import logging
import math
from collections import deque
from datetime import datetime
from logging.handlers import RotatingFileHandler

from core.util.time_util import TIMEZONE_INFO

logger = logging.getLogger(__name__)

_outlier_file_handler_cache: dict[str, RotatingFileHandler] = {}


def _get_outlier_file_logger(log_path: str) -> logging.Logger:
    """Return a dedicated logger for the outlier file, created once per path."""
    logger_name = f"outlier_file:{log_path}"
    outlier_logger = logging.getLogger(logger_name)

    if log_path not in _outlier_file_handler_cache:
        handler = RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        outlier_logger.addHandler(handler)
        outlier_logger.setLevel(logging.INFO)
        outlier_logger.propagate = False
        _outlier_file_handler_cache[log_path] = handler

    return outlier_logger


def _percentile(values: list[float], percentage: float) -> float:
    """Calculate the p-th percentile using linear interpolation (no numpy required)."""
    sorted_values = sorted(values)
    total_count = len(sorted_values)

    index = (total_count - 1) * percentage / 100.0
    lower_bound_index = int(index)
    upper_bound_index = lower_bound_index + 1

    if upper_bound_index >= total_count:
        return sorted_values[lower_bound_index]

    fraction = index - lower_bound_index
    return sorted_values[lower_bound_index] * (1.0 - fraction) + sorted_values[upper_bound_index] * fraction


class SnapshotAggregator:
    """
    Per-device rolling buffer with IQR-based outlier filtering and mean aggregation.

    Used by alert and control evaluator subscribers when eval_interval > monitor_interval.

    Buffer capacity is auto-calculated: max_capacity = ceil(eval_interval / monitor_interval).
    After each successful evaluation the caller must call clear(device_id).
    """

    def __init__(
        self,
        monitor_interval: float,
        eval_interval: float,
        outlier_log_path: str = "logs/outlier.log",
    ) -> None:
        self.monitor_interval = monitor_interval
        self.eval_interval = eval_interval
        self._max_capacity: int = math.ceil(eval_interval / monitor_interval)

        # device_id -> deque of (snapshot_dict, iso_timestamp)
        self._device_snapshots: dict[str, deque[tuple[dict[str, float], str]]] = {}

        self._outlier_log_path = outlier_log_path
        self._outlier_file_logger = _get_outlier_file_logger(outlier_log_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def max_capacity(self) -> int:
        return self._max_capacity

    def push(
        self,
        device_id: str,
        snapshot: dict[str, float],
        timestamp: str | None = None,
    ) -> None:
        """Push a snapshot into the rolling buffer for *device_id*."""
        if device_id not in self._device_snapshots:
            self._device_snapshots[device_id] = deque(maxlen=self._max_capacity)

        current_timestamp = timestamp or datetime.now(TIMEZONE_INFO).isoformat()
        self._device_snapshots[device_id].append((snapshot, current_timestamp))

    def aggregate(self, device_id: str) -> dict[str, float] | None:
        """
        Aggregate the buffer for *device_id* using IQR-filtered mean.

        Returns:
            Aggregated snapshot dict, or None when evaluation should be skipped
            (all values for at least one parameter were outliers).
        """
        snapshot_entries = list(self._device_snapshots.get(device_id, []))
        if not snapshot_entries:
            return None

        # Collect all unique parameter names
        unique_parameters: set[str] = set()
        for snapshot, _ in snapshot_entries:
            unique_parameters.update(snapshot.keys())

        aggregated_result: dict[str, float] = {}

        for parameter_name in unique_parameters:
            parameter_values: list[float] = []
            recorded_timestamps: list[str] = []

            for snapshot, timestamp in snapshot_entries:
                if parameter_name in snapshot:
                    parameter_values.append(snapshot[parameter_name])
                    recorded_timestamps.append(timestamp)

            if not parameter_values:
                continue

            if len(parameter_values) < 3:
                # Not enough data for IQR – use plain mean
                aggregated_result[parameter_name] = sum(parameter_values) / len(parameter_values)
            else:
                filtered_values = self._iqr_filter(parameter_values, recorded_timestamps, device_id, parameter_name)

                if not filtered_values:
                    # All values were outliers – skip entire evaluation
                    logger.warning(
                        f"[Aggregation] device_id={device_id} parameter={parameter_name} "
                        "all values were outliers, evaluation skipped"
                    )
                    return None

                aggregated_result[parameter_name] = sum(filtered_values) / len(filtered_values)

        return aggregated_result

    def clear(self, device_id: str) -> None:
        """Clear the rolling buffer for *device_id* after evaluation."""
        self._device_snapshots.pop(device_id, None)

    def buffer_size(self, device_id: str) -> int:
        """Return the current number of buffered snapshots for *device_id*."""
        return len(self._device_snapshots.get(device_id, []))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _iqr_filter(
        self,
        values: list[float],
        timestamps: list[str],
        device_id: str,
        parameter_name: str,
    ) -> list[float]:
        """
        Apply IQR outlier filtering.

        Values outside [Q1 - 1.5·IQR, Q3 + 1.5·IQR] are excluded.
        Each excluded value is logged to journalctl (WARNING) and the outlier file.

        Returns the list of non-outlier values.
        """
        first_quartile = _percentile(values, 25)
        third_quartile = _percentile(values, 75)
        interquartile_range = third_quartile - first_quartile

        lower_fence = first_quartile - 1.5 * interquartile_range
        upper_fence = third_quartile + 1.5 * interquartile_range

        filtered_values: list[float] = []

        for value, timestamp in zip(values, timestamps):
            if lower_fence <= value <= upper_fence:
                filtered_values.append(value)
            else:
                # journalctl WARNING
                logger.warning(
                    f"[Outlier] device_id={device_id} parameter={parameter_name} "
                    f"value={value:.4f} timestamp={timestamp} excluded from aggregation"
                )
                # Dedicated outlier log file (JSON per line)
                outlier_record = {
                    "timestamp": timestamp,
                    "device_id": device_id,
                    "parameter": parameter_name,
                    "value": value,
                    "q1": first_quartile,
                    "q3": third_quartile,
                    "iqr_lower": lower_fence,
                    "iqr_upper": upper_fence,
                }
                self._outlier_file_logger.info(json.dumps(outlier_record))

        return filtered_values
