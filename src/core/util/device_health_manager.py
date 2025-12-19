"""
Device Health Manager with Quick Health Check

Centralized health status tracking for all devices with quick health check support.
Shared across Monitor, WebSocket, and API services.
"""

import asyncio
import logging
import math
from dataclasses import dataclass

from core.device.generic.generic_device import AsyncGenericModbusDevice
from core.model.device_constant import DEFAULT_MISSING_VALUE
from core.model.enum.health_check_strategy_enum import HealthCheckStrategyEnum
from core.schema.health_check_config_schema import HealthCheckConfig
from core.util.time_util import now_timestamp

logger = logging.getLogger("DeviceHealthManager")


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


@dataclass
class HealthCheckResult:
    """Result of a quick health check operation"""

    device_id: str
    is_online: bool
    elapsed_ms: float
    strategy: str
    attempt: int = 1
    error_msg: str | None = None

    def __repr__(self):
        status = "ONLINE" if self.is_online else "OFFLINE"
        msg = f"HealthCheckResult({self.device_id}: {status}, {self.elapsed_ms:.1f}ms, attempt={self.attempt})"
        if self.error_msg:
            msg += f", error={self.error_msg}"
        return msg


class DeviceHealthManager:
    """
    Centralized device health tracking with quick health check support.

    Typical usage in monitor loop:
        ok, reason = await health.should_poll(device_id)
        if not ok: skip
        try:
            ...
            await health.mark_success(device_id)
        except:
            await health.mark_failure(device_id)

    Quick health check usage (in recovery window):
        if should_recover:
            is_online, result = await health.quick_health_check(device_id)
            if is_online:
                # Device recovered, do full read
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

        self._health_check_configs: dict[str, HealthCheckConfig] = {}

    def register_device(self, device_id: str) -> None:
        if device_id not in self._health_status:
            self._health_status[device_id] = DeviceHealthStatus(device_id=device_id)
            logger.debug(f"Registered device for health tracking: {device_id}")

    async def should_poll(self, device_id: str) -> tuple[bool, str]:
        """
        Decide whether the device should be polled now.
        Returns (allowed, reason).
        """
        now_ts = now_timestamp()

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
        now_ts = now_timestamp()
        async with self._lock:
            if device_id not in self._health_status:
                self.register_device(device_id)

            status: DeviceHealthStatus = self._health_status[device_id]
            was_unhealthy: bool = not status.is_healthy
            status.mark_success(now_ts)

            if was_unhealthy:
                logger.info(f"Device {device_id} recovered (ONLINE)")

    async def mark_failure(self, device_id: str) -> None:
        now_ts = now_timestamp()
        async with self._lock:
            if device_id not in self._health_status:
                self.register_device(device_id)

            status: DeviceHealthStatus = self._health_status[device_id]
            was_healthy: bool = status.is_healthy

            status.mark_failure(now_ts)

            # Apply "mark unhealthy" threshold (default: 1)
            if status.consecutive_failures >= self._mark_unhealthy_after_failures:
                status.is_healthy = False

            # Compute next cooldown
            cooldown_sec: float = self._compute_cooldown_sec(status.consecutive_failures)
            status.next_allowed_poll_ts = now_ts + cooldown_sec

            if was_healthy:
                logger.warning(
                    f"Device {device_id} marked unhealthy (failures={status.consecutive_failures}, cooldown={cooldown_sec:.1f}s)"
                )
            else:
                logger.info(
                    f"Device {device_id} still unhealthy (failures={status.consecutive_failures}, cooldown={cooldown_sec:.1f}s)"
                )

    def is_healthy(self, device_id: str) -> bool:
        status = self._health_status.get(device_id)
        return True if status is None else status.is_healthy

    def get_status(self, device_id: str) -> dict | None:
        status = self._health_status.get(device_id)
        if status is None:
            return None
        return self._to_summary(status)

    def get_all_summary(self) -> dict[str, dict]:
        return {device_id: self._to_summary(status) for device_id, status in self._health_status.items()}

    def get_unhealthy_devices(self) -> list[str]:
        return [device_id for device_id, status in self._health_status.items() if not status.is_healthy]

    def register_health_check_config(self, device_id: str, config: HealthCheckConfig) -> None:
        """Register health check configuration for a device"""
        self._health_check_configs[device_id] = config
        logger.info(f"[{device_id}] Health check: {config.to_summary()}")

    def get_health_check_summary(self) -> dict:
        """
        Get summary of health check configurations.

        Returns:
            {
                "total_devices": int,
                "configured_devices": int,
                "strategies": {"single_register": int, "partial_bulk": int, "full_read": int}
            }
        """
        strategy_dict = {"single_register": 0, "partial_bulk": 0, "full_read": 0}

        for config in self._health_check_configs.values():
            strategy_dict[config.strategy.value] += 1

        return {
            "total_devices": len(self._health_status),
            "configured_devices": len(self._health_check_configs),
            "strategies": strategy_dict,
        }

    async def quick_health_check(
        self, device: AsyncGenericModbusDevice, device_id: str
    ) -> tuple[bool, HealthCheckResult | None]:
        """
        Perform quick health check on a device.

        Args:
            device: Device instance to check
            device_id: Device identifier (format: "MODEL_SLAVEID")

        Returns:
            (is_online, result)
        """

        # Get health check config
        config: HealthCheckConfig | None = self._health_check_configs.get(device_id)
        if not config:
            logger.debug(f"[{device_id}] No health check config, skipping quick check")
            return False, None

        # Execute health check
        result: HealthCheckResult = await self._perform_health_check(device, device_id, config)

        # Update health status
        if result.is_online:
            await self.mark_success(device_id)
        else:
            await self.mark_failure(device_id)

        return result.is_online, result

    def _compute_cooldown_sec(self, failures: int) -> float:
        """
        Exponential backoff: base * factor^(failures-1), capped at max.
        failures starts from 1.
        """
        failure_count: int = max(1, int(failures))
        backoff_sec: float = self._base_cooldown_sec * (self._backoff_factor ** (failure_count - 1))
        capped_cooldown_sec: float = min(backoff_sec, self._max_cooldown_sec)

        # Optional jitter to avoid synchronization (keep deterministic if jitter_sec=0)
        if self._jitter_sec > 0:
            # simple bounded jitter without random dependency:
            # use fractional part of time as pseudo jitter source
            frac = math.modf(now_timestamp())[0]
            capped_cooldown_sec: float = capped_cooldown_sec + (frac * 2 - 1) * self._jitter_sec  # [-jitter, +jitter]
            capped_cooldown_sec: float = max(0.0, capped_cooldown_sec)

        return capped_cooldown_sec

    def _to_summary(self, health_status: DeviceHealthStatus) -> dict:
        now_ts = now_timestamp()
        return {
            "device_id": health_status.device_id,
            "is_healthy": health_status.is_healthy,
            "consecutive_failures": health_status.consecutive_failures,
            "last_success_ts": health_status.last_success_ts,
            "last_failure_ts": health_status.last_failure_ts,
            "last_check_ts": health_status.last_check_ts,
            "next_allowed_poll_ts": health_status.next_allowed_poll_ts,
            "cooldown_remaining_sec": (
                max(0.0, health_status.next_allowed_poll_ts - now_ts) if not health_status.is_healthy else 0.0
            ),
        }

    async def _perform_health_check(self, device, device_id: str, config: HealthCheckConfig) -> HealthCheckResult:
        """
        Internal method to perform the actual health check.
        """

        start_time: float = asyncio.get_running_loop().time()
        is_online = False
        attempt = 0
        error_msg = None

        for attempt in range(config.retry_on_failure + 1):
            try:
                if config.strategy == HealthCheckStrategyEnum.SINGLE_REGISTER:
                    is_online = await self._check_single_register(device, config, attempt)
                elif config.strategy == HealthCheckStrategyEnum.PARTIAL_BULK:
                    is_online = await self._check_partial_bulk(device, config, attempt)
                elif config.strategy == HealthCheckStrategyEnum.FULL_READ:
                    is_online = await self._check_full_read(device, attempt)
                else:
                    logger.error(f"[{device_id}] Unknown health check strategy: {config.strategy}")
                    is_online = await self._check_full_read(device, attempt)

                if is_online:
                    break  # Success, no need to retry

                # If offline and not last attempt, wait before retry
                if attempt < config.retry_on_failure:
                    await asyncio.sleep(0.05)  # 50ms between retries

            except asyncio.TimeoutError:
                error_msg = "timeout"
                if attempt >= config.retry_on_failure:
                    is_online = False
            except Exception as e:
                error_msg = str(e)
                logger.debug(f"[{device_id}] Health check attempt {attempt+1} exception: {e}")
                if attempt >= config.retry_on_failure:
                    is_online = False

        elapsed_ms = (asyncio.get_running_loop().time() - start_time) * 1000

        return HealthCheckResult(
            device_id=device_id,
            is_online=is_online,
            elapsed_ms=elapsed_ms,
            strategy=config.strategy.value,
            attempt=attempt + 1,
            error_msg=error_msg,
        )

    async def _check_single_register(
        self, device: AsyncGenericModbusDevice, config: HealthCheckConfig, attempt: int
    ) -> bool:
        """Check device health by reading a single register"""
        register_name: str | None = config.registers[0]
        if not register_name:
            logger.error("single_register strategy requires register name")
            return False

        try:
            value = await asyncio.wait_for(device.read_value(register_name), timeout=config.timeout_sec)
            is_valid = value != DEFAULT_MISSING_VALUE and value is not None

            if attempt == 0 and logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Health check [{register_name}]: value={value}, valid={is_valid}")

            return is_valid

        except asyncio.TimeoutError:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Health check [{register_name}]: timeout after {config.timeout_sec}s")
            raise
        except Exception as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Health check [{register_name}]: exception {e}")
            raise

    async def _check_partial_bulk(
        self, device: AsyncGenericModbusDevice, config: HealthCheckConfig, attempt: int
    ) -> bool:
        """Check device health by reading a few registers"""
        register_names = config.registers
        if not register_names:
            logger.error("partial_bulk strategy requires register names")
            return False

        try:
            # Read multiple registers concurrently
            tasks = [asyncio.wait_for(device.read_value(name), timeout=config.timeout_sec) for name in register_names]
            values = await asyncio.gather(*tasks, return_exceptions=True)

            # Count valid values
            valid_count = sum(
                1
                for value in values
                if not isinstance(value, Exception) and value != DEFAULT_MISSING_VALUE and value is not None
            )

            is_online = valid_count > 0

            if attempt == 0 and logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Health check [{', '.join(register_names)}]: valid={valid_count}/{len(register_names)}")

            return is_online

        except asyncio.TimeoutError:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Health check partial_bulk: timeout after {config.timeout_sec}s")
            raise
        except Exception as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Health check partial_bulk: exception {e}")
            raise

    async def _check_full_read(self, device: AsyncGenericModbusDevice, attempt: int) -> bool:
        """Check device health by reading all registers (fallback)"""
        try:
            values = await device.read_all()
            is_online = any(
                v != DEFAULT_MISSING_VALUE and v is not None for v in values.values() if isinstance(v, (int, float))
            )

            if attempt == 0 and logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Health check full_read: online={is_online}")

            return is_online

        except Exception as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Health check full_read: exception {e}")
            raise

    # ==================== Static Helper ====================

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
