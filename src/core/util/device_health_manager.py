"""
Device Health Manager

Centralized health status tracking for all devices.
Shared across Monitor, WebSocket, and API services.
"""

import asyncio
import logging
import math
from dataclasses import dataclass
from datetime import datetime

from core.util.time_util import TIMEZONE_INFO

logger = logging.getLogger("DeviceHealthManager")


def _now_timestamp() -> float:
    """Monotonic-ish wall clock seconds (epoch). Good enough for cooldown decisions."""
    return datetime.now(tz=TIMEZONE_INFO).timestamp()


@dataclass
class DeviceHealthStatus:
    device_id: str

    # Core health
    is_healthy: bool = True
    consecutive_failures: int = 0

    # Timestamps (epoch seconds)
    last_success_ts: float | None = None
    last_failure_ts: float | None = None
    last_check_ts: float | None = None  # last time we evaluated/attempted a poll

    # Cooldown control
    next_allowed_poll_ts: float = 0.0

    def mark_success(self, now_ts: float) -> None:
        self.is_healthy = True
        self.last_success_ts = now_ts
        self.consecutive_failures = 0
        self.next_allowed_poll_ts = 0.0  # allow immediate polling
        self.last_check_ts = now_ts

    def mark_failure(self, now_ts: float) -> None:
        self.last_failure_ts = now_ts
        self.consecutive_failures += 1
        self.is_healthy = False
        self.last_check_ts = now_ts


class DeviceHealthManager:
    """
    Centralized device health tracking.

    Typical usage in monitor loop:
        ok, reason = await health.should_poll(device_id)
        if not ok: skip
        try:
            ...
            await health.mark_success(device_id)
        except:
            await health.mark_failure(device_id)
    """

    def __init__(
        self,
        *,
        base_cooldown_sec: float = 60.0,
        max_cooldown_sec: float = 600.0,
        backoff_factor: float = 2.0,
        jitter_sec: float = 0.0,
        mark_unhealthy_after_failures: int = 1,
    ):
        self._health_status: dict[str, DeviceHealthStatus] = {}
        self._lock = asyncio.Lock()

        # Backoff policy
        self._base_cooldown_sec = float(base_cooldown_sec)
        self._max_cooldown_sec = float(max_cooldown_sec)
        self._backoff_factor = float(backoff_factor)
        self._jitter_sec = float(jitter_sec)
        self._mark_unhealthy_after_failures = int(mark_unhealthy_after_failures)

    def register_device(self, device_id: str) -> None:
        if device_id not in self._health_status:
            self._health_status[device_id] = DeviceHealthStatus(device_id=device_id)
            logger.debug(f"Registered device for health tracking: {device_id}")

    async def should_poll(self, device_id: str) -> tuple[bool, str]:
        """
        Decide whether the device should be polled now.
        Returns (allowed, reason).
        """
        now_ts = _now_timestamp()

        async with self._lock:
            if device_id not in self._health_status:
                self.register_device(device_id)

            st = self._health_status[device_id]
            st.last_check_ts = now_ts

            # Healthy devices: always allow
            if st.is_healthy:
                return True, "healthy"

            # Unhealthy devices: gate by cooldown
            if now_ts < st.next_allowed_poll_ts:
                wait = st.next_allowed_poll_ts - now_ts
                return False, f"cooldown({wait:.1f}s)"

            return True, "recovery_window"

    async def mark_success(self, device_id: str) -> None:
        now_ts = _now_timestamp()
        async with self._lock:
            if device_id not in self._health_status:
                self.register_device(device_id)

            st = self._health_status[device_id]
            was_unhealthy = not st.is_healthy
            st.mark_success(now_ts)

            if was_unhealthy:
                logger.info(f"Device {device_id} recovered (ONLINE)")

    async def mark_failure(self, device_id: str) -> None:
        now_ts = _now_timestamp()
        async with self._lock:
            if device_id not in self._health_status:
                self.register_device(device_id)

            st = self._health_status[device_id]
            was_healthy = st.is_healthy

            st.mark_failure(now_ts)

            # Apply "mark unhealthy" threshold (default: 1)
            if st.consecutive_failures >= self._mark_unhealthy_after_failures:
                st.is_healthy = False

            # Compute next cooldown
            cooldown = self._compute_cooldown_sec(st.consecutive_failures)
            st.next_allowed_poll_ts = now_ts + cooldown

            if was_healthy:
                logger.warning(
                    f"Device {device_id} marked unhealthy (failures={st.consecutive_failures}, cooldown={cooldown:.1f}s)"
                )
            else:
                logger.info(
                    f"Device {device_id} still unhealthy (failures={st.consecutive_failures}, cooldown={cooldown:.1f}s)"
                )

    def _compute_cooldown_sec(self, failures: int) -> float:
        """
        Exponential backoff: base * factor^(failures-1), capped at max.
        failures starts from 1.
        """
        f = max(1, int(failures))
        raw = self._base_cooldown_sec * (self._backoff_factor ** (f - 1))
        cooldown = min(raw, self._max_cooldown_sec)

        # Optional jitter to avoid synchronization (keep deterministic if jitter_sec=0)
        if self._jitter_sec > 0:
            # simple bounded jitter without random dependency:
            # use fractional part of time as pseudo jitter source
            frac = math.modf(_now_timestamp())[0]
            cooldown = cooldown + (frac * 2 - 1) * self._jitter_sec  # [-jitter, +jitter]
            cooldown = max(0.0, cooldown)

        return cooldown

    def is_healthy(self, device_id: str) -> bool:
        st = self._health_status.get(device_id)
        return True if st is None else st.is_healthy

    def get_status(self, device_id: str) -> dict | None:
        st = self._health_status.get(device_id)
        if st is None:
            return None
        return self._to_summary(st)

    def get_all_status(self) -> dict[str, dict]:
        return {did: self._to_summary(st) for did, st in self._health_status.items()}

    def get_unhealthy_devices(self) -> list[str]:
        return [did for did, st in self._health_status.items() if not st.is_healthy]

    def _to_summary(self, st: DeviceHealthStatus) -> dict:
        now_timestamp = _now_timestamp()
        return {
            "device_id": st.device_id,
            "is_healthy": st.is_healthy,
            "consecutive_failures": st.consecutive_failures,
            "last_success_ts": st.last_success_ts,
            "last_failure_ts": st.last_failure_ts,
            "last_check_ts": st.last_check_ts,
            "next_allowed_poll_ts": st.next_allowed_poll_ts,
            "cooldown_remaining_sec": max(0.0, st.next_allowed_poll_ts - now_timestamp) if not st.is_healthy else 0.0,
        }

    @staticmethod
    def calculate_health_params(poll_interval: float) -> dict:
        """
        Automatically calculate Health Manager parameters based on polling interval

        Args:
            poll_interval: Polling interval (seconds)

        Returns:
            Health Manager parameter dictionary

        Configuration strategy:
            - Faster polling → smaller base cooldown multiplier, higher failure tolerance
            - Slower polling → larger base cooldown multiplier, longer maximum cooldown
        """
        if poll_interval <= 1.0:
            # High-frequency polling (≤ 1 second)
            return {
                "base_cooldown_sec": 2.0,  # 2x
                "max_cooldown_sec": 180.0,  # 3 minutes
                "backoff_factor": 2.0,
                "jitter_sec": 0.2,  # 20%
                "mark_unhealthy_after_failures": 2,  # tolerate 1 failure
            }

        if poll_interval <= 5.0:
            # Medium-frequency polling (1–5 seconds)
            return {
                "base_cooldown_sec": poll_interval * 2.0,
                "max_cooldown_sec": 300.0,  # 5 minutes
                "backoff_factor": 2.0,
                "jitter_sec": poll_interval * 0.2,
                "mark_unhealthy_after_failures": 1,
            }

        if poll_interval <= 10.0:
            # Standard polling (5–10 seconds)
            return {
                "base_cooldown_sec": poll_interval * 3.0,
                "max_cooldown_sec": 600.0,  # 10 minutes
                "backoff_factor": 2.0,
                "jitter_sec": poll_interval * 0.2,
                "mark_unhealthy_after_failures": 1,
            }

        # Low-frequency polling (> 10 seconds)
        return {
            "base_cooldown_sec": poll_interval * 2.0,
            "max_cooldown_sec": 600.0,
            "backoff_factor": 2.0,
            "jitter_sec": poll_interval * 0.2,
            "mark_unhealthy_after_failures": 1,
        }
