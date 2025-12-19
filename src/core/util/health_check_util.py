import logging

from core.device.health_check_strategy_inferencer import HealthCheckStrategyInferencer
from core.schema.constraint_schema import ConstraintConfigSchema
from core.schema.health_check_config_schema import HealthCheckConfig
from core.util.config_manager import ConfigManager
from core.util.device_health_manager import DeviceHealthManager
from device_manager import AsyncDeviceManager

logger = logging.getLogger("HealthCheckUtil")


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
    """Use health check to write startup frequencies"""
    logger.info("Applying startup frequencies with health check...")

    written_count = 0
    skipped_count = 0
    failed_count = 0

    for device in device_manager.device_list:
        device_id = f"{device.model}_{device.slave_id}"

        # Get startup frequency
        startup_freq = ConfigManager.get_device_startup_frequency(
            config=constraint_schema, model=device.model, slave_id=device.slave_id
        )

        if not startup_freq:
            continue

        try:
            # Health check
            is_online, health_result = await health_manager.quick_health_check(device=device, device_id=device_id)

            if not is_online:
                logger.debug(
                    f"[{device_id}] Device offline "
                    f"(check: {health_result.elapsed_ms:.0f}ms if health_result else 0), skip"
                )
                skipped_count += 1
                continue

            # Check constraint
            final_freq: float = startup_freq
            if not device.constraints.allow("RW_HZ", startup_freq):
                hz_constraint = device.constraints.constraints.get("RW_HZ")
                if hz_constraint and hz_constraint.min:
                    final_freq = hz_constraint.min
                    logger.warning(
                        f"[{device_id}] Startup frequency {startup_freq} Hz "
                        f"outside constraints, using {final_freq} Hz"
                    )

            # Write value
            await device.write_value("RW_HZ", final_freq)
            written_count += 1

            logger.info(
                f"[{device_id}] Startup frequency applied: {final_freq} Hz "
                f"(check: {health_result.elapsed_ms:.0f if health_result else 0}ms)"
            )

        except Exception as exc:
            failed_count += 1
            logger.warning(f"[{device_id}] Failed to write startup frequency: {exc}")

    logger.info(
        f"Startup frequency summary: {written_count} written, "
        f"{skipped_count} skipped (offline), {failed_count} failed"
    )
