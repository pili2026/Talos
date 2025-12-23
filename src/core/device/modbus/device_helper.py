import asyncio
import logging
from typing import Any

from core.device.generic.modbus_bus import ModbusBus
from core.device.generic.scales import ScaleService
from core.model.device_constant import DEFAULT_MISSING_VALUE
from core.util.data_decoder import DecodeFormat

# ==================== Module-level utility functions ====================


def required_word_count(fmt: str | DecodeFormat) -> int:
    """
    Calculate required word count for a decode format.

    Args:
        fmt: Decode format (string or DecodeFormat enum)

    Returns:
        Number of 16-bit words required (1 or 2)
    """
    if isinstance(fmt, str):
        try:
            fmt = DecodeFormat(fmt.lower())
        except ValueError:
            return 1

    match fmt:
        case (
            DecodeFormat.U32
            | DecodeFormat.U32_LE
            | DecodeFormat.U32_BE
            | DecodeFormat.F32
            | DecodeFormat.F32_LE
            | DecodeFormat.F32_BE
            | DecodeFormat.F32_BE_SWAP
        ):
            return 2
        case _:
            return 1


class ModbusDeviceHelper:
    """Helper utilities for Modbus device operations."""

    def __init__(
        self,
        model: str,
        slave_id: int,
        register_map: dict,
        scales: ScaleService,
        client: Any,
        port_lock: asyncio.Lock,
        logger: logging.Logger,
    ):
        self.model = model
        self.slave_id = slave_id
        self.register_map = register_map
        self.scales = scales
        self.client = client
        self.port_lock = port_lock
        self.logger = logger

    def require_readable(self, name: str) -> dict:
        """Get readable pin config or empty dict."""
        cfg = self.register_map.get(name) or {}
        if not cfg.get("readable"):
            self.logger.warning(f"[{self.model}] register_map {name} is not readable")
            return {}
        return cfg

    def require_writable(self, name: str) -> dict:
        """Get writable pin config or empty dict."""
        cfg = self.register_map.get(name) or {}
        if not cfg.get("writable"):
            self.logger.warning(f"[{self.model}] register_map {name} is not writable")
            return {}
        return cfg

    def default_offline_snapshot(self) -> dict[str, float | int]:
        """Generate default snapshot with all -1 values for offline device."""
        return {name: DEFAULT_MISSING_VALUE for name, cfg in self.register_map.items() if cfg.get("readable")}

    def scaled_raw_value(self, pin_cfg: dict, value: int | float) -> int:
        """Convert scaled value back to raw register value."""
        scale = float(pin_cfg.get("scale", 1.0))
        return int(round(float(value) / scale))

    def get_bus_for_pin(self, pin_name: str, default_register_type: str, bus_cache: dict) -> ModbusBus:
        """
        Get or create ModbusBus for a specific pin's register type.

        Args:
            pin_name: Pin name
            default_register_type: Device default register type
            bus_cache: Cache dict to store created buses

        Returns:
            ModbusBus instance for the pin
        """
        pin_def: dict = self.register_map.get(pin_name)
        if not pin_def:
            return bus_cache[default_register_type]

        pin_register_type: str = pin_def.get("register_type", default_register_type)

        if pin_register_type in bus_cache:
            return bus_cache[pin_register_type]

        bus_slave_id = (
            int(self.slave_id) if isinstance(self.slave_id, str) and self.slave_id.isdigit() else int(self.slave_id)
        )

        new_bus = ModbusBus(
            client=self.client,
            slave_id=bus_slave_id,
            register_type=pin_register_type,
            lock=self.port_lock,
        )
        bus_cache[pin_register_type] = new_bus

        self.logger.info(
            f"[{self.model}_{self.slave_id}] Created ModbusBus for pin '{pin_name}' "
            f"with register_type='{pin_register_type}'"
        )

        return new_bus

    async def resolve_dynamic_scale(self, scale_from: str, bus: ModbusBus) -> float:
        """Resolve dynamic scale factor from device registers."""

        async def index_reader(index_name: str) -> int:
            pin = self.register_map.get(index_name)
            if not pin:
                self.logger.warning(f"[{self.model}] index '{index_name}' not defined; fallback -1")
                return DEFAULT_MISSING_VALUE
            try:
                return await bus.read_u16(pin["offset"])
            except Exception as e:
                self.logger.warning(f"[{self.model}] read index '{index_name}' failed: {e}")
                return DEFAULT_MISSING_VALUE

        mapping = {
            "current_index": "current",
            "voltage_index": "voltage",
            "energy_index": "energy_auto",
            "kwh_scale": "kwh",
        }
        kind = mapping.get(scale_from)
        if not kind:
            self.logger.warning(f"[{self.model}] Unknown scale_from '{scale_from}'")
            return 1.0
        return await self.scales.get_factor(kind, index_reader)
