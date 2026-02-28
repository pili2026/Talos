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


def _percentile(values: list[float], p: float) -> float:
    """Calculate the p-th percentile using linear interpolation (no numpy required)."""
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    index = (n - 1) * p / 100.0
    lower = int(index)
    upper = lower + 1
    if upper >= n:
        return sorted_vals[lower]
    frac = index - lower
    return sorted_vals[lower] * (1.0 - frac) + sorted_vals[upper] * frac


class SnapshotAggregator:
    """
    Per-device rolling buffer with IQR-based outlier filtering and mean aggregation.

    Used by alert and control evaluator subscribers when eval_interval > monitor_interval.

    Buffer size is auto-calculated: maxlen = ceil(eval_interval / monitor_interval).
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
        self._maxlen: int = math.ceil(eval_interval / monitor_interval)

        # device_id -> deque of (snapshot_dict, iso_timestamp)
        self._buffers: dict[str, deque[tuple[dict[str, float], str]]] = {}

        self._outlier_log_path = outlier_log_path
        self._outlier_file_logger = _get_outlier_file_logger(outlier_log_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def maxlen(self) -> int:
        return self._maxlen

    def push(
        self,
        device_id: str,
        snapshot: dict[str, float],
        timestamp: str | None = None,
    ) -> None:
        """Push a snapshot into the rolling buffer for *device_id*."""
        if device_id not in self._buffers:
            self._buffers[device_id] = deque(maxlen=self._maxlen)
        ts = timestamp or datetime.now(TIMEZONE_INFO).isoformat()
        self._buffers[device_id].append((snapshot, ts))

    def aggregate(self, device_id: str) -> dict[str, float] | None:
        """
        Aggregate the buffer for *device_id* using IQR-filtered mean.

        Returns:
            Aggregated snapshot dict, or None when evaluation should be skipped
            (all values for at least one parameter were outliers).
        """
        entries = list(self._buffers.get(device_id, []))
        if not entries:
            return None

        # Collect all parameter names
        all_params: set[str] = set()
        for snapshot, _ in entries:
            all_params.update(snapshot.keys())

        aggregated: dict[str, float] = {}
        for param in all_params:
            values: list[float] = []
            timestamps: list[str] = []
            for snapshot, ts in entries:
                if param in snapshot:
                    values.append(snapshot[param])
                    timestamps.append(ts)

            if not values:
                continue

            if len(values) < 3:
                # Not enough data for IQR – use plain mean
                aggregated[param] = sum(values) / len(values)
            else:
                filtered = self._iqr_filter(values, timestamps, device_id, param)
                if not filtered:
                    # All values were outliers – skip entire evaluation
                    logger.warning(
                        f"[Aggregation] device_id={device_id} parameter={param} "
                        "all values were outliers, evaluation skipped"
                    )
                    return None
                aggregated[param] = sum(filtered) / len(filtered)

        return aggregated

    def clear(self, device_id: str) -> None:
        """Clear the rolling buffer for *device_id* after evaluation."""
        self._buffers.pop(device_id, None)

    def buffer_size(self, device_id: str) -> int:
        """Return the current number of buffered snapshots for *device_id*."""
        return len(self._buffers.get(device_id, []))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _iqr_filter(
        self,
        values: list[float],
        timestamps: list[str],
        device_id: str,
        param: str,
    ) -> list[float]:
        """
        Apply IQR outlier filtering.

        Values outside [Q1 - 1.5·IQR, Q3 + 1.5·IQR] are excluded.
        Each excluded value is logged to journalctl (WARNING) and the outlier file.

        Returns the list of non-outlier values.
        """
        q1 = _percentile(values, 25)
        q3 = _percentile(values, 75)
        iqr = q3 - q1
        lower_fence = q1 - 1.5 * iqr
        upper_fence = q3 + 1.5 * iqr

        filtered: list[float] = []
        for v, ts in zip(values, timestamps):
            if lower_fence <= v <= upper_fence:
                filtered.append(v)
            else:
                # journalctl WARNING
                logger.warning(
                    f"[Outlier] device_id={device_id} parameter={param} "
                    f"value={v:.4f} timestamp={ts} excluded from aggregation"
                )
                # Dedicated outlier log file (JSON per line)
                record = {
                    "timestamp": ts,
                    "device_id": device_id,
                    "parameter": param,
                    "value": v,
                    "q1": q1,
                    "q3": q3,
                    "iqr_lower": lower_fence,
                    "iqr_upper": upper_fence,
                }
                self._outlier_file_logger.info(json.dumps(record))

        return filtered
