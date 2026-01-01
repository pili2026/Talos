"""
Health Check Strategy Inference Engine

Automatically infers optimal health check strategy for devices
based on their register map and device type.
"""

import logging

from core.model.enum.health_check_strategy_enum import HealthCheckStrategyEnum
from core.model.enum.register_type_enum import RegisterType
from core.schema.health_check_config_schema import HealthCheckConfig

logger = logging.getLogger("HealthCheckInference")


class HealthCheckStrategyInferencer:
    """
    Infers optimal health check strategy based on device characteristics.

    Inference Rules (in priority order):
    1. Search for STATUS registers (INVSTATUS, STATUS, COMM_STATUS, etc.)
    2. VFD/Inverter: use smallest offset readable register (excluding RW_*)
    3. AI/DI modules: use first 2-3 contiguous pins
    4. Power Meters: use first 3 contiguous registers
    5. Default: use smallest offset readable register
    """

    # Keywords for status registers (case-insensitive)
    STATUS_KEYWORDS = [
        "INVSTATUS",
        "STATUS",
        "COMM_STATUS",
        "DEVICE_STATUS",
        "READY",
        "ONLINE_FLAG",
        "DEVICE_READY",
        "ALARM",
    ]

    @classmethod
    def infer(
        cls,
        device_model: str,
        device_type: str,
        register_map: dict,
        default_register_type: RegisterType = RegisterType.HOLDING,
    ) -> HealthCheckConfig | None:
        """
        Infer health check strategy for a device.

        Args:
            device_model: Device model name (e.g., "TECO_VFD")
            device_type: Device type (e.g., "inverter", "ai_module")
            register_map: Device register map
            default_register_type: Default Modbus register type

        Returns:
            HealthCheckConfig or None (fallback to full_read)
        """
        if not register_map:
            logger.warning(f"[{device_model}] No register map, cannot infer health check strategy")
            return None

        # Rule 1: Search for STATUS registers
        status_config = cls._find_status_register(register_map, default_register_type)
        if status_config:
            logger.info(f"[{device_model}] Inferred: {status_config.to_summary()}")
            return status_config

        # Rule 2-5: Device-type specific strategies
        if device_type in ["inverter", "vfd"]:
            config = cls._infer_inverter_strategy(register_map, default_register_type)
        elif device_type in ["ai_module", "di_module", "io_module"]:
            config = cls._infer_io_module_strategy(register_map, default_register_type)
        elif device_type == "power_meter":
            config = cls._infer_power_meter_strategy(register_map, default_register_type)
        else:
            config = cls._infer_default_strategy(register_map, default_register_type)

        if config:
            logger.info(f"[{device_model}] Inferred: {config.to_summary()}")
        else:
            logger.warning(f"[{device_model}] Could not infer strategy, will use full_read")

        return config

    @classmethod
    def _find_status_register(cls, register_map: dict, default_register_type: RegisterType) -> HealthCheckConfig | None:
        """Search for STATUS-like registers (Rule 1)"""
        for keyword in cls.STATUS_KEYWORDS:
            for name, cfg in register_map.items():
                if keyword.lower() in name.lower() and cfg.get("readable"):
                    register_type = cfg.get("register_type", default_register_type)
                    return HealthCheckConfig(
                        strategy=HealthCheckStrategyEnum.SINGLE_REGISTER,
                        register=name,
                        register_type=RegisterType(register_type),
                        retry_on_failure=1,
                        timeout_sec=1.5,  # > modbus timeout (1.0)
                        reason=f"Found status register: {name}",
                    )
        return None

    @classmethod
    def _infer_inverter_strategy(
        cls, register_map: dict, default_register_type: RegisterType
    ) -> HealthCheckConfig | None:
        """
        Inverter strategy (Rule 2):
        Use smallest offset readable register (excluding RW_* control registers and computed fields)
        """
        readable_regs = []
        for name, cfg in register_map.items():
            # Skip computed fields
            if cfg.get("type") == "computed":
                continue

            # Exclude control registers
            if cfg.get("readable") and not name.startswith("RW_"):
                offset = cfg.get("offset")
                if offset is not None:
                    register_type = cfg.get("register_type", default_register_type)
                    readable_regs.append((name, offset, register_type))

        if not readable_regs:
            return None

        # Sort by offset, pick smallest
        readable_regs.sort(key=lambda x: x[1])
        name, offset, register_type = readable_regs[0]

        return HealthCheckConfig(
            strategy=HealthCheckStrategyEnum.SINGLE_REGISTER,
            register=name,
            register_type=RegisterType(register_type),
            retry_on_failure=1,
            timeout_sec=1.5,
            reason=f"Inverter: smallest offset register {name} (offset {offset})",
        )

    @classmethod
    def _infer_io_module_strategy(
        cls, register_map: dict, default_register_type: RegisterType
    ) -> HealthCheckConfig | None:
        """
        I/O module strategy (Rule 3):
        Use first 2-3 contiguous pins (PHYSICAL registers only)
        """
        readable_regs = []
        for name, cfg in register_map.items():
            # CRITICAL: Skip computed fields
            if cfg.get("type") == "computed":
                continue

            if cfg.get("readable"):
                offset = cfg.get("offset")
                if offset is not None:
                    register_type = cfg.get("register_type", default_register_type)
                    readable_regs.append((name, offset, register_type))

        if not readable_regs:
            return None

        # Sort by offset
        readable_regs.sort(key=lambda x: x[1])

        # Check for bit-packed registers (e.g., SD500: all pins at offset 0)
        if len(readable_regs) > 1 and readable_regs[0][1] == readable_regs[1][1]:
            # Bit-packed → single register read
            name, offset, register_type = readable_regs[0]
            return HealthCheckConfig(
                strategy=HealthCheckStrategyEnum.SINGLE_REGISTER,
                register=name,
                register_type=RegisterType(register_type),
                retry_on_failure=1,
                timeout_sec=1.5,
                reason=f"I/O module: bit-packed register {name} (offset {offset})",
            )

        # Take first 2-3 contiguous pins
        take_count = min(3, len(readable_regs))
        first_n = readable_regs[:take_count]

        # Check if reasonably contiguous (within 10 offsets)
        if take_count > 1:
            offset_diff = first_n[-1][1] - first_n[0][1]
            if offset_diff > 10:
                # Not contiguous, use single register
                name, offset, register_type = first_n[0]
                return HealthCheckConfig(
                    strategy=HealthCheckStrategyEnum.SINGLE_REGISTER,
                    register=name,
                    register_type=RegisterType(register_type),
                    retry_on_failure=1,
                    timeout_sec=1.5,
                    reason=f"I/O module: non-contiguous, using first pin {name}",
                )

        # Contiguous pins
        names = [name for name, _, _ in first_n]
        register_type = first_n[0][2]

        return HealthCheckConfig(
            strategy=HealthCheckStrategyEnum.PARTIAL_BULK,
            registers=names,
            register_type=RegisterType(register_type),
            retry_on_failure=1,
            timeout_sec=1.5,
            reason=f"I/O module: first {len(names)} contiguous pins",
        )

    @classmethod
    def _infer_power_meter_strategy(
        cls, register_map: dict, default_register_type: RegisterType
    ) -> HealthCheckConfig | None:
        """
        Power meter strategy (Rule 4):
        Use first 3 contiguous registers (PHYSICAL registers only)
        """
        readable_regs = []
        for name, cfg in register_map.items():
            # CRITICAL: Skip computed fields
            if cfg.get("type") == "computed":
                continue

            if cfg.get("readable"):
                offset = cfg.get("offset")
                if offset is not None:
                    register_type = cfg.get("register_type", default_register_type)
                    readable_regs.append((name, offset, register_type))

        if not readable_regs:
            return None

        # Sort by offset
        readable_regs.sort(key=lambda x: x[1])

        # Take first 3 (or fewer)
        take_count = min(3, len(readable_regs))
        first_n = readable_regs[:take_count]

        if take_count == 1:
            # Only one register
            name, offset, register_type = first_n[0]
            return HealthCheckConfig(
                strategy=HealthCheckStrategyEnum.SINGLE_REGISTER,
                register=name,
                register_type=RegisterType(register_type),
                retry_on_failure=1,
                timeout_sec=1.5,
                reason=f"Power meter: single available register {name}",
            )

        # Multiple registers
        names = [name for name, _, _ in first_n]
        register_type = first_n[0][2]

        return HealthCheckConfig(
            strategy=HealthCheckStrategyEnum.PARTIAL_BULK,
            registers=names,
            register_type=RegisterType(register_type),
            retry_on_failure=1,
            timeout_sec=1.5,
            reason=f"Power meter: first {len(names)} registers",
        )

    @classmethod
    def _infer_default_strategy(
        cls, register_map: dict, default_register_type: RegisterType
    ) -> HealthCheckConfig | None:
        """
        Default strategy (Rule 5):
        Use smallest offset readable register (PHYSICAL registers only)
        """
        readable_regs = []
        for name, cfg in register_map.items():
            # CRITICAL: Skip computed fields
            if cfg.get("type") == "computed":
                continue

            if cfg.get("readable"):
                offset = cfg.get("offset")
                if offset is not None:
                    register_type = cfg.get("register_type", default_register_type)
                    readable_regs.append((name, offset, register_type))

        if not readable_regs:
            return None

        # Sort by offset, pick smallest
        readable_regs.sort(key=lambda x: x[1])
        name, offset, register_type = readable_regs[0]

        return HealthCheckConfig(
            strategy=HealthCheckStrategyEnum.SINGLE_REGISTER,
            register=name,
            register_type=RegisterType(register_type),
            retry_on_failure=1,
            timeout_sec=1.5,
            reason=f"Default: smallest offset register {name} (offset {offset})",
        )
