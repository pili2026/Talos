import logging
from dataclasses import dataclass

from core.device.generic.generic_device import AsyncGenericModbusDevice
from core.device.health_check_strategy_inferencer import HealthCheckStrategyInferencer
from core.schema.constraint_schema import ConstraintConfigSchema
from core.schema.health_check_config_schema import HealthCheckConfig
from core.util.config_manager import ConfigManager
from core.util.device_health_manager import DeviceHealthManager
from device_manager import AsyncDeviceManager

logger = logging.getLogger("HealthCheckUtil")


@dataclass
class InitStats:
    hz_written: int = 0
    turned_on: int = 0
    skipped_offline: int = 0
    failed: int = 0
    turn_on_failed: int = 0

    def __str__(self) -> str:
        return (
            f"hz_written={self.hz_written}, turned_on={self.turned_on}, "
            f"skipped_offline={self.skipped_offline}, failed={self.failed}, "
            f"turn_on_failed={self.turn_on_failed}"
        )


def initialize_health_check_configs(
    device_manager: AsyncDeviceManager,
    health_manager: DeviceHealthManager,
):
    """Initialize health check configurations"""

    logger.info("=" * 60)
    logger.info("Initializing Health Check Strategies")
    logger.info("=" * 60)

    for device in device_manager.device_list:
        device_id: str = f"{device.model}_{device.slave_id}"

        health_check_raw: dict | None = device.get_health_check_config()

        if health_check_raw:
            try:
                health_check_config = HealthCheckConfig(**health_check_raw)
            except Exception as e:
                logger.warning(f"[{device_id}] Invalid health_check config: {e}")
                health_check_config = None
        else:
            health_check_config = None

        if not health_check_config:
            health_check_config = HealthCheckStrategyInferencer.infer(
                device_model=device.model,
                device_type=device.device_type,
                register_map=device.register_map,
                default_register_type=device.register_type,
            )

        if health_check_config:
            health_manager.register_health_check_config(device_id, health_check_config)
        else:
            logger.warning(f"[{device_id}] No health check strategy, will use full read_all()")

    summary: dict = health_manager.get_health_check_summary()
    logger.info(f"Configured: {summary['configured_devices']}/{summary['total_devices']} devices")
    logger.info(f"Strategies: {summary['strategies']}")
    logger.info("=" * 60)


async def apply_startup_frequencies_with_health_check(
    device_manager: AsyncDeviceManager,
    health_manager: DeviceHealthManager,
    constraint_schema: ConstraintConfigSchema,
):
    """Use health check to write startup frequencies (+ optional auto turn on)."""
    logger.info("Applying startup initialization with health check...")

    stats = InitStats()

    for device in device_manager.device_list:
        device_id = f"{device.model}_{device.slave_id}"

        startup_freq: float | None = ConfigManager.get_device_startup_frequency(
            constraint_schema, device.model, device.slave_id
        )
        auto_turn_on: bool | None = ConfigManager.get_device_auto_turn_on(
            constraint_schema, device.model, device.slave_id
        )

        if not (startup_freq or auto_turn_on):
            continue

        try:
            is_online, health_result = await health_manager.quick_health_check(device=device, device_id=device_id)
            elapsed_ms = health_result.elapsed_ms if health_result else 0.0

            if not is_online:
                logger.debug(f"[{device_id}] offline (check: {elapsed_ms:.0f}ms), skip")
                stats.skipped_offline += 1
                continue

            if startup_freq is not None:
                await _apply_frequency(device, device_id, startup_freq, stats, elapsed_ms)

            if auto_turn_on:
                await _apply_turn_on(device, device_id, stats)

        except Exception as exc:
            stats.failed += 1
            logger.warning(f"[{device_id}] init failed: {exc}")

    logger.info(f"Startup init summary: {stats}")


async def perform_initial_health_check_for_all_devices(
    device_manager: AsyncDeviceManager, health_manager: DeviceHealthManager
) -> dict[str, int]:
    """
    Perform initial health check on all devices during startup.

    This ensures offline devices are marked as unhealthy BEFORE monitor starts,
    preventing Monitor from attempting slow read_all() on each parameter.

    Returns:
        Dict with counts: {"online": int, "offline": int, "failed": int}
    """
    logger.info("=" * 60)
    logger.info("Performing Initial Health Check for All Devices")
    logger.info("=" * 60)

    stats = {"online": 0, "offline": 0, "failed": 0}

    for device in device_manager.device_list:
        device_id = f"{device.model}_{device.slave_id}"

        try:
            is_online, health_result = await health_manager.quick_health_check(device=device, device_id=device_id)

            if is_online:
                stats["online"] += 1
                logger.info(
                    f"[{device_id}] ✓ ONLINE "
                    f"(check: {health_result.elapsed_ms:.0f}ms, "
                    f"strategy: {health_result.strategy})"
                )
            else:
                stats["offline"] += 1
                logger.warning(
                    f"[{device_id}] ✗ OFFLINE "
                    f"(check: {health_result.elapsed_ms:.0f}ms, "
                    f"strategy: {health_result.strategy})"
                )

        except Exception as exc:
            stats["failed"] += 1
            logger.warning(f"[{device_id}] Health check failed: {exc}")
            # Mark as failure so Monitor won't try full read
            await health_manager.mark_failure(device_id)

    logger.info("=" * 60)
    logger.info(
        f"Initial Health Check Complete: "
        f"{stats['online']} online, {stats['offline']} offline, {stats['failed']} failed"
    )
    logger.info("=" * 60)

    return stats


async def _apply_frequency(
    device: AsyncGenericModbusDevice, device_id: str, startup_freq: float, stats: InitStats, elapsed_ms: float
):
    """Apply startup frequency with constraint checking."""
    final_freq = startup_freq

    if not device.constraints.allow("RW_HZ", startup_freq):
        hz_constraint = device.constraints.constraints.get("RW_HZ")
        if hz_constraint and hz_constraint.min is not None:
            final_freq = hz_constraint.min
            logger.warning(
                f"[{device_id}] startup_frequency={startup_freq} outside constraints, " f"use min={final_freq}"
            )

    await device.write_value("RW_HZ", final_freq)
    stats.hz_written += 1
    logger.info(f"[{device_id}] startup RW_HZ={final_freq} (check: {elapsed_ms:.0f}ms)")


async def _apply_turn_on(device: AsyncGenericModbusDevice, device_id: str, stats: InitStats):
    """Apply auto turn on if device supports it."""
    control_reg = device.get_control_register()
    if not control_reg:
        logger.warning(f"[{device_id}] auto_turn_on=true but no control register")
        return

    try:
        if await device.is_running():
            logger.info(f"[{device_id}] already ON ({control_reg}=1), skip")
            return

        await device.write_value(control_reg, 1)
        stats.turned_on += 1
        logger.info(f"[{device_id}] auto_turn_on applied ({control_reg}=1)")

    except Exception as exc:
        stats.turn_on_failed += 1
        logger.warning(f"[{device_id}] auto_turn_on failed: {exc}")
