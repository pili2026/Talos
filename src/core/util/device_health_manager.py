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
from core.model.device_constant import DEFAULT_MISSING_VALUE, INVERTER
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

    first_failure_ts: float | None = None
    last_recovery_attempt_ts: float | None = None

    # Device-specific backoff parameters (None = use global default value)
    base_cooldown_sec: float | None = None
    max_cooldown_sec: float | None = None
    backoff_factor: float | None = None
    mark_unhealthy_after_failures: int | None = None

    def mark_success(self, now_ts: float) -> None:
        self.is_healthy = True
        self.last_success_ts = now_ts
        self.consecutive_failures = 0
        self.next_allowed_poll_ts = 0.0  # allow immediate polling
        self.last_check_ts = now_ts

        self.first_failure_ts = None
        self.last_recovery_attempt_ts = None

    def mark_failure(self, now_ts: float) -> None:
        self.last_failure_ts = now_ts
        self.consecutive_failures += 1
        self.is_healthy = False
        self.last_check_ts = now_ts

        if self.first_failure_ts is None:
            self.first_failure_ts = now_ts


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


# TODO: Nedd to Refactor
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

    CRITICAL_DEVICE_TYPES = {INVERTER}  # For Inverter device

    def __init__(
        self,
        *,
        base_cooldown_sec: float = 60.0,
        max_cooldown_sec: float = 180.0,
        backoff_factor: float = 2.0,
        jitter_sec: float = 0.0,
        mark_unhealthy_after_failures: int = 1,
        long_term_offline_threshold_sec: float = 3600.0,
        max_failures_cap: int = 5,
    ):
        self._health_status: dict[str, DeviceHealthStatus] = {}
        self._lock = asyncio.Lock()

        # Backoff policy
        self._default_base_cooldown_sec = float(base_cooldown_sec)
        self._default_max_cooldown_sec = float(max_cooldown_sec)
        self._default_backoff_factor = float(backoff_factor)
        self._jitter_sec = float(jitter_sec)
        self._default_mark_unhealthy_after_failures = int(mark_unhealthy_after_failures)

        self._long_term_offline_threshold = float(long_term_offline_threshold_sec)
        self._max_failures_cap = int(max_failures_cap)

        self._health_check_configs: dict[str, HealthCheckConfig] = {}

        self._critical_backoff_params: dict = {
            "base_cooldown_sec": 10.0,
            "max_cooldown_sec": 10.0,
            "backoff_factor": 1.0,
            "mark_unhealthy_after_failures": 1,
        }

    def configure_for_device_list(self, device_list: list, poll_interval: float) -> None:
        """
        Configure health manager for a specific device list.
        Automatically calculates optimal parameters for critical devices based on count.

        Args:
            device_list: List of devices (must have device_type attribute)
            poll_interval: Monitor polling interval in seconds
        """
        # Count critical devices
        critical_device_count: int = sum(
            1 for device in device_list if device.device_type in self.CRITICAL_DEVICE_TYPES
        )

        if critical_device_count > 0:
            # Calculate optimal parameters
            critical_params = self.calculate_critical_params(
                device_count=critical_device_count, poll_interval=poll_interval
            )

            self._critical_backoff_params = critical_params

            logger.info("=" * 60)
            logger.info("Critical Device Configuration")
            logger.info(f"  Device count: {critical_device_count}")
            logger.info(f"  Estimated poll time: {critical_device_count * 1.2:.1f}s")
            logger.info(f"  Base cooldown: {critical_params['base_cooldown_sec']:.1f}s")
            logger.info(f"  Max cooldown: {critical_params['max_cooldown_sec']:.1f}s")
            logger.info("=" * 60)
        else:
            logger.info("No critical devices found, using default parameters")

    @property
    def critical_backoff_params(self) -> dict:
        """Get current critical device backoff parameters"""
        return self._critical_backoff_params

    @critical_backoff_params.setter
    def critical_backoff_params(self, value: dict) -> None:
        """Set critical device backoff parameters (for backward compatibility)"""
        self._critical_backoff_params = value

    def register_device(self, device_id: str, device_type: str | None = None) -> None:
        """
        Register device with automatic parameter selection based on device type.

        Args:
            device_id: Device identifier (format: "MODEL_SLAVEID")
            device_type: Device type from driver config (e.g., "inverter", "sensor", "io_module")
                        If None, uses default parameters.

        Critical device types (e.g., "inverter") get aggressive recovery parameters.
        """
        if device_id not in self._health_status:
            # Determine if critical device
            is_critical: bool = device_type in self.CRITICAL_DEVICE_TYPES if device_type else False

            if is_critical:
                status = DeviceHealthStatus(
                    device_id=device_id,
                    base_cooldown_sec=self._critical_backoff_params["base_cooldown_sec"],
                    max_cooldown_sec=self._critical_backoff_params["max_cooldown_sec"],
                    backoff_factor=self._critical_backoff_params["backoff_factor"],
                    mark_unhealthy_after_failures=self._critical_backoff_params["mark_unhealthy_after_failures"],
                )
                logger.info(
                    f"Registered CRITICAL device: {device_id} (type={device_type}, "
                    f"base_cooldown={self._critical_backoff_params['base_cooldown_sec']}s)"
                )
            else:
                status = DeviceHealthStatus(device_id=device_id)
                logger.debug(f"Registered device: {device_id} (type={device_type or 'unknown'})")

            self._health_status[device_id] = status

    async def should_poll(self, device_id: str) -> tuple[bool, str]:
        """
        Decide whether the device should be polled now.
        Returns (allowed, reason).
        """
        now_ts = now_timestamp()

        async with self._lock:
            if device_id not in self._health_status:
                self.register_device(device_id)

            health_status = self._health_status[device_id]
            health_status.last_check_ts = now_ts

            # Healthy devices: always allow
            if health_status.is_healthy:
                return True, "healthy"

            # Unhealthy devices: gate by cooldown
            if now_ts < health_status.next_allowed_poll_ts:
                wait = health_status.next_allowed_poll_ts - now_ts
                return False, f"cooldown({wait:.1f}s)"

            health_status.last_recovery_attempt_ts = now_ts

            # Record long-term offline entry
            if health_status.first_failure_ts:
                offline_duration = now_ts - health_status.first_failure_ts
                if offline_duration > self._long_term_offline_threshold:
                    logger.debug(
                        f"[{device_id}] Long-term offline device entering recovery "
                        f"({offline_duration/3600:.1f}h offline)"
                    )

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

            is_critical = self._is_critical_device(status)

            if not is_critical and status.first_failure_ts:
                offline_duration = now_ts - status.first_failure_ts

                # Regular devices：Long-term offline cap failures
                if offline_duration > self._long_term_offline_threshold:
                    if status.consecutive_failures > self._max_failures_cap:
                        old_failures = status.consecutive_failures
                        status.consecutive_failures = self._max_failures_cap

                        logger.info(
                            f"[{device_id}] Long-term offline "
                            f"({offline_duration/3600:.1f}h), "
                            f"capping failures: {old_failures} → {self._max_failures_cap}"
                        )

                        # Reset timer to avoid being stuck in this logic
                        status.first_failure_ts = now_ts

            failure_threshold: int = (
                status.mark_unhealthy_after_failures
                if status.mark_unhealthy_after_failures is not None
                else self._default_mark_unhealthy_after_failures
            )

            # Apply "mark unhealthy" threshold (default: 1)
            if status.consecutive_failures >= failure_threshold:
                status.is_healthy = False

            # Compute next cooldown
            cooldown_sec: float = self._compute_cooldown_sec(status)
            status.next_allowed_poll_ts = now_ts + cooldown_sec

            if was_healthy:
                logger.warning(
                    f"Device {device_id} marked unhealthy (failures={status.consecutive_failures}, cooldown={cooldown_sec:.1f}s)"
                )
            else:
                logger.debug(
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

        config: HealthCheckConfig | None = self._health_check_configs.get(device_id)

        # 1) No config -> fallback probe (do NOT treat as offline by default)
        if not config:
            result = await self._fallback_quick_probe(device=device, device_id=device_id)

            if result.is_online:
                await self.mark_success(device_id)
            else:
                await self.mark_failure(device_id)

            return result.is_online, result

        # 2) Normal path with config
        result: HealthCheckResult = await self._perform_health_check(device, device_id, config)

        if result.is_online:
            await self.mark_success(device_id)
        else:
            await self.mark_failure(device_id)

        return result.is_online, result

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

    async def _fallback_quick_probe(self, device: AsyncGenericModbusDevice, device_id: str) -> bool:
        """
        Fallback probe when no HealthCheckConfig is provided.

        Policy:
        1) If device has any readable register, read the first one with a short timeout.
        2) If no readable register exists:
            - read_all() with at least one non-missing value -> ONLINE
            - all values missing (-1) -> OFFLINE
        """

        # 1) Pick first readable pin from register_map if possible
        try:
            register_name: str | None = None
            reg_map = getattr(device, "register_map", None) or {}
            for name, cfg in reg_map.items():
                if isinstance(cfg, dict) and cfg.get("readable"):
                    register_name = name
                    break

            if register_name:
                # short timeout probe
                v = await asyncio.wait_for(device.read_value(register_name), timeout=0.3)
                return (v is not None) and (v != DEFAULT_MISSING_VALUE)

        except Exception as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"[{device_id}] fallback probe(read_value) failed: {e}")

        # 2) If cannot pick a readable pin, fallback to read_all() and judge by exception + content
        try:
            values = await asyncio.wait_for(device.read_all(), timeout=0.6)

            # If we got any non-missing numeric value -> online
            for v in (values or {}).values():
                if v is None:
                    continue
                if isinstance(v, (int, float)) and v != DEFAULT_MISSING_VALUE:
                    return True

            # All missing (-1 / None) -> offline
            return False

        except Exception as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"[{device_id}] fallback probe(read_all) failed: {e}")
            return False

    @staticmethod
    def _pick_first_readable_pin(device: AsyncGenericModbusDevice) -> str | None:
        reg_map = getattr(device, "register_map", None) or {}
        for name, cfg in reg_map.items():
            try:
                if cfg.get("readable"):
                    return name
            except Exception:
                continue
        return None

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

        registers = config.registers or []
        if not registers:
            logger.warning("single_register strategy has no registers configured; " "fallback to full_read probe")
            return await self._check_full_read(device, attempt)

        register_name: str | None = registers[0]
        if not register_name:
            logger.warning("single_register strategy first register is empty; " "fallback to full_read probe")
            return await self._check_full_read(device, attempt)

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
        register_names: list[str] = config.registers or []
        if not register_names:
            logger.error("partial_bulk strategy requires register names")
            return False

        # Sequential check: one success is enough
        for name in register_names:
            try:
                value = await asyncio.wait_for(device.read_value(name), timeout=config.timeout_sec)
                if value != DEFAULT_MISSING_VALUE and value is not None:
                    if attempt == 0 and logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"Health check [{name}]: value={value} -> ONLINE")
                    return True
            except Exception as e:
                # ignore and continue to next register
                if attempt == 0 and logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"Health check [{name}]: exception {e}")

        if attempt == 0 and logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Health check [{', '.join(register_names)}]: all failed -> OFFLINE")
        return False

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

    def _is_critical_device(self, status: DeviceHealthStatus) -> bool:
        """
        Determine if a device is critical based on its backoff factor.
        """
        backoff: float = status.backoff_factor if status.backoff_factor is not None else self._default_backoff_factor
        return backoff <= 1.0

    def _compute_cooldown_sec(self, status: DeviceHealthStatus) -> float:
        """
        Exponential backoff: base * factor^(failures-1), capped at max.
        MUST NOT raise OverflowError.
        """
        base_cooldown: float = (
            status.base_cooldown_sec if status.base_cooldown_sec is not None else self._default_base_cooldown_sec
        )

        max_cooldown: float = (
            status.max_cooldown_sec if status.max_cooldown_sec is not None else self._default_max_cooldown_sec
        )

        backoff_factor: float = (
            status.backoff_factor if status.backoff_factor is not None else self._default_backoff_factor
        )

        failure_count: int = max(1, int(status.consecutive_failures))
        exp = failure_count - 1

        # If factor <= 1, no exponential growth; just base capped.
        if backoff_factor <= 1.0:
            cooldown_sec = min(float(base_cooldown), float(max_cooldown))
        else:
            # Clamp exponent to avoid float overflow:
            # log(base) + exp*log(factor) <= log(max_float) ~= 709.78
            try:
                log_max = 709.782712893384  # approx log(sys.float_info.max)
                log_base = math.log(base_cooldown) if base_cooldown > 0 else -math.inf
                log_factor = math.log(backoff_factor)

                exp_max = int((log_max - log_base) / log_factor) if log_factor > 0 else 0
                safe_exp = min(exp, max(0, exp_max))

                if safe_exp < exp:
                    logger.warning(
                        f"[{status.device_id}] backoff exponent clamped: "
                        f"failures={failure_count}, exp={exp} -> {safe_exp}, "
                        f"base={base_cooldown}, factor={backoff_factor}, max_cd={max_cooldown}"
                    )

                try:
                    backoff_sec = base_cooldown * (backoff_factor**safe_exp)
                except OverflowError:
                    backoff_sec = max_cooldown

                cooldown_sec = min(backoff_sec, max_cooldown)

            except Exception as e:
                # Absolute safety fallback: never crash health manager.
                logger.warning(f"[{status.device_id}] backoff compute fallback due to error: {e}")
                cooldown_sec = min(float(base_cooldown), float(max_cooldown))

        # Optional jitter
        if self._jitter_sec > 0:
            frac = math.modf(now_timestamp())[0]
            cooldown_sec = cooldown_sec + (frac * 2 - 1) * self._jitter_sec
            cooldown_sec = max(0.0, cooldown_sec)

        return float(cooldown_sec)

    # ==================== Static Helper ====================

    @staticmethod
    def calculate_health_params(poll_interval: float) -> dict:
        """
        Automatically calculate Health Manager parameters based on polling interval.

        CHANGED: Reduced max_cooldown_sec for regular devices:
            - High-frequency (≤1s): 180s → 120s (2 minutes)
            - Medium-frequency (1-5s): 300s → 180s (3 minutes)
            - Standard (5-10s): 600s → 180s (3 minutes)

        This prevents long-term offline devices from becoming "permanently offline".
        Critical devices (inverters) are unaffected - they maintain fixed cooldown.
        """
        if poll_interval <= 1.0:
            # High-frequency polling (≤ 1 second)
            return {
                "base_cooldown_sec": 2.0,  # 2x
                "max_cooldown_sec": 120.0,  # 2 minutes
                "backoff_factor": 2.0,
                "jitter_sec": 0.2,  # 20%
                "mark_unhealthy_after_failures": 2,  # tolerate 1 failure
            }

        if poll_interval <= 5.0:
            # Medium-frequency polling (1–5 seconds)
            return {
                "base_cooldown_sec": poll_interval * 2.0,
                "max_cooldown_sec": 180.0,  # 3 minutes
                "backoff_factor": 2.0,
                "jitter_sec": poll_interval * 0.2,
                "mark_unhealthy_after_failures": 1,
            }

        if poll_interval <= 10.0:
            # Standard polling (5–10 seconds)
            return {
                "base_cooldown_sec": poll_interval * 3.0,
                "max_cooldown_sec": 180.0,  # 3 minutes
                "backoff_factor": 2.0,
                "jitter_sec": poll_interval * 0.2,
                "mark_unhealthy_after_failures": 1,
            }

        # Low-frequency polling (> 10 seconds)
        return {
            "base_cooldown_sec": poll_interval * 2.0,
            "max_cooldown_sec": 180.0,  # 3 minutes
            "backoff_factor": 2.0,
            "jitter_sec": poll_interval * 0.2,
            "mark_unhealthy_after_failures": 1,
        }

    @staticmethod
    def calculate_critical_params(device_count: int, poll_interval: float) -> dict:
        """
        Calculate backoff parameters for critical devices based on device count.

        Critical devices (e.g., inverters) need fast recovery but must account for
        RS-485 sequential polling time when multiple devices share the same bus.

        Args:
            device_count: Number of critical devices on the RS-485 bus
            poll_interval: Monitor polling interval (seconds)

        Returns:
            Dictionary with backoff parameters optimized for the device count

        Algorithm:
            - Single device polling time: ~1.2s (health check + RS-485 delay)
            - Total polling time: device_count × 1.2s
            - Base cooldown: total_polling_time × 1.2 (20% buffer)
            - Minimum: poll_interval (never less than the monitor cycle)

        Examples:
            - 2 devices: ~3s cooldown
            - 10 devices: ~15s cooldown
            - 20 devices: ~30s cooldown
        """
        if device_count <= 0:
            # No critical devices, return default
            return {
                "base_cooldown_sec": 10.0,
                "max_cooldown_sec": 10.0,
                "backoff_factor": 1.0,
                "mark_unhealthy_after_failures": 1,
            }

        # Estimated time per device (health check + RS-485 frame delay)
        per_device_time = 1.2  # seconds

        # Total time to poll all critical devices sequentially
        total_poll_time = device_count * per_device_time

        # Add 20% buffer for overhead (logging, processing, etc.)
        base_cooldown = total_poll_time * 1.2

        # Ensure cooldown is at least equal to the monitor polling interval
        base_cooldown = max(base_cooldown, poll_interval)

        # Round to 1 decimal place for cleaner logs
        base_cooldown = round(base_cooldown, 1)

        return {
            "base_cooldown_sec": base_cooldown,
            "max_cooldown_sec": base_cooldown * 2,  # Allow some exponential growth
            "backoff_factor": 1.0,  # No exponential backoff for critical devices
            "mark_unhealthy_after_failures": 1,
        }
