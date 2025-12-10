"""
Device Health Manager

Centralized health status tracking for all devices.
Shared across Monitor, WebSocket, and API services.
"""

import asyncio
import logging
from datetime import datetime

from core.util.time_util import TIMEZONE_INFO

logger = logging.getLogger("DeviceHealthManager")


class DeviceHealthStatus:
    """Health status for a single device."""

    def __init__(self, device_id: str):
        self.device_id = device_id
        self.is_healthy = True
        self.last_success_time: float | None = None
        self.last_failure_time: float | None = None
        self.consecutive_failures = 0
        self.last_check_time: float | None = None

    def mark_success(self):
        """Mark device as healthy after successful read."""
        self.is_healthy = True
        self.last_success_time = datetime.now(TIMEZONE_INFO)
        self.consecutive_failures = 0

    def mark_failure(self):
        """Mark device as unhealthy after failed read."""
        self.last_failure_time = datetime.now(TIMEZONE_INFO)
        self.consecutive_failures += 1

        # Mark unhealthy after 1 consecutive failures
        if self.consecutive_failures >= 1:
            self.is_healthy = False

        logger.info(f"Device failures: {self.consecutive_failures}, is_healthy: {self.is_healthy}")

    def get_status_summary(self) -> dict:
        """Get status summary for API/logging."""
        return {
            "device_id": self.device_id,
            "is_healthy": self.is_healthy,
            "consecutive_failures": self.consecutive_failures,
            "last_success": self.last_success_time,
            "last_failure": self.last_failure_time,
        }


class DeviceHealthManager:
    """
    Centralized device health tracking.

    Shared singleton across Monitor, WebSocket, and API services.
    """

    def __init__(self):
        self._health_status: dict[str, DeviceHealthStatus] = {}
        self._lock = asyncio.Lock()

    def register_device(self, device_id: str) -> None:
        """Register a device for health tracking."""
        if device_id not in self._health_status:
            self._health_status[device_id] = DeviceHealthStatus(device_id)
            logger.debug(f"Registered device for health tracking: {device_id}")

    async def mark_success(self, device_id: str) -> None:
        """Mark device as healthy after successful operation."""
        async with self._lock:
            if device_id not in self._health_status:
                self.register_device(device_id)

            status = self._health_status[device_id]
            was_unhealthy = not status.is_healthy

            status.mark_success()

            if was_unhealthy:
                logger.info(f"Device {device_id} recovered (ONLINE)")

    async def mark_failure(self, device_id: str) -> None:
        """Mark device as unhealthy after failed operation."""
        async with self._lock:
            if device_id not in self._health_status:
                self.register_device(device_id)

            status = self._health_status[device_id]
            was_healthy = status.is_healthy

            status.mark_failure()

            if was_healthy and not status.is_healthy:
                logger.warning(f"Device {device_id} marked unhealthy " f"(failures: {status.consecutive_failures})")

    def is_healthy(self, device_id: str) -> bool:
        """Check if device is healthy."""
        if device_id not in self._health_status:
            # Unknown device, assume healthy
            return True
        return self._health_status[device_id].is_healthy

    def get_status(self, device_id: str) -> dict | None:
        """Get health status for a device."""
        if device_id not in self._health_status:
            return None
        return self._health_status[device_id].get_status_summary()

    def get_all_status(self) -> dict[str, dict]:
        """Get health status for all devices."""
        return {device_id: status.get_status_summary() for device_id, status in self._health_status.items()}

    def get_unhealthy_devices(self) -> list[str]:
        """Get list of unhealthy device IDs."""
        return [device_id for device_id, status in self._health_status.items() if not status.is_healthy]
