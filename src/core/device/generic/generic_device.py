import asyncio
from typing import Any

from pymodbus.client import AsyncModbusSerialClient

from core.device.base import BaseDevice
from core.device.generic.computed_field_processor import ComputedFieldProcessor
from core.device.generic.constraints_policy import ConstraintPolicy
from core.device.generic.hooks import HookManager
from core.device.generic.modbus_bus import ModbusBus
from core.device.generic.scales import ScaleService
from core.device.modbus.bulk_reader import ModbusBulkReader
from core.device.modbus.device_helper import ModbusDeviceHelper
from core.device.modbus.register_handler import ModbusRegisterHandler
from core.model.device_constant import DEFAULT_MISSING_VALUE, REG_RW_ON_OFF
from core.model.enum.register_type_enum import RegisterType
from core.util.value_decoder import ValueDecoder


class AsyncGenericModbusDevice(BaseDevice):
    """
    Modbus RTU device implementation with bulk read optimization.

    Delegates specialized operations to:
    - ModbusBulkReader: Bulk read optimization
    - ModbusRegisterHandler: Low-level register operations
    - ModbusDeviceHelpers: Utility functions
    """

    def __init__(
        self,
        model: str,
        client: AsyncModbusSerialClient,
        slave_id: int | str,
        register_type: str,
        register_map: dict,
        device_type: str,
        model_config: dict | None = None,
        *,
        port: str,
        constraint_policy: ConstraintPolicy | None = None,
        table_dict: dict | None = None,
        mode_dict: dict | None = None,
        write_hooks: list | dict | None = None,
        port_lock: asyncio.Lock | None = None,
    ):
        # Initialize base class
        super().__init__(model, slave_id, device_type, register_map)

        # Modbus-specific attributes
        self.client = client
        self.register_type = register_type
        self.port = str(port)
        self._port_lock = port_lock

        # Create default ModbusBus
        bus_slave_id = (
            int(self.slave_id) if isinstance(self.slave_id, str) and self.slave_id.isdigit() else int(self.slave_id)
        )
        self.bus = ModbusBus(client=client, slave_id=bus_slave_id, register_type=register_type, lock=self._port_lock)
        self._bus_cache: dict[str, ModbusBus] = {register_type: self.bus}

        self.logger.debug(f"[{self.model}_{self.slave_id}] Initialized with default register_type='{register_type}'")

        # Configuration processing (backward compat)
        table_dict = table_dict if table_dict is not None else register_map.pop("tables", {})
        mode_dict = mode_dict if mode_dict is not None else register_map.pop("modes", {})

        # Initialize services
        self.scales = ScaleService(table_dict=table_dict, mode_dict=mode_dict, logger=self.logger)
        self.constraints = constraint_policy or ConstraintPolicy(constraints=None, logger=self.logger)
        hook_list: list = write_hooks if write_hooks is not None else register_map.pop("write_hooks", [])
        self.hooks = HookManager(hook_list=hook_list, logger=self.logger, scale_service=self.scales)

        self.decoder = ValueDecoder()
        self.computed_processor = ComputedFieldProcessor(register_map)

        if self.computed_processor.has_computed_fields():
            self.logger.info(
                f"[{self.model}] Computed fields enabled: {list(self.computed_processor.computed_fields.keys())}"
            )

        # Initialize specialized handlers
        self.bulk_reader = ModbusBulkReader(register_map, register_type, self.logger)
        self.register_handler = ModbusRegisterHandler(model, register_map, self.bus, self.logger)
        self.helpers = ModbusDeviceHelper(model, slave_id, register_map, self.scales, client, port_lock, self.logger)

        self._model_config = model_config

    # ==================== Override base class methods ====================

    def supports_on_off(self) -> bool:
        """Check if device supports on/off control."""
        if self.get_control_register():
            return True
        return str(self.device_type).lower() in {"inverter", "vfd", "inverter_vfd"}

    def get_health_check_config(self) -> dict | None:
        """Get health check configuration from device model definition."""
        if not isinstance(self._model_config, dict):
            return None

        health_check = self._model_config.get("health_check")
        if health_check and isinstance(health_check, dict):
            return health_check

        return None

    # ==================== Public read/write methods ====================

    async def read_all(self) -> dict[str, Any]:
        if not await self.bus.ensure_connected():
            self.logger.warning("[OFFLINE] default bus not connected; return default -1 snapshot")
            return self.helpers.default_offline_snapshot()

        result: dict[str, Any] = {}

        bulk_ranges = self.bulk_reader.build_bulk_ranges(max_regs_per_req=120)
        bulk_failed = bool(bulk_ranges)

        for bulk_range in bulk_ranges:
            bus = await self._get_or_create_bus(bulk_range.register_type)

            try:
                registers = await bus.read_value_by_type(bulk_range.start, bulk_range.count)
                registers = list(registers)
                bulk_failed = False  # ★ any success → device alive

            except Exception as exc:
                self.logger.warning(
                    f"[{self.model}:{self.slave_id}] Bulk read failed "
                    f"rt={bulk_range.register_type} start={bulk_range.start} count={bulk_range.count}: {exc}"
                )
                for pin_name, _ in bulk_range.items:
                    result[pin_name] = DEFAULT_MISSING_VALUE
                continue

            bulk_results = self.bulk_reader.process_bulk_range_result(
                bulk_range, registers, self.register_handler.is_invalid_raw
            )
            result.update(bulk_results)

        if bulk_failed:
            self.logger.warning(
                f"[{self.model}:{self.slave_id}] All bulk reads failed; treat device as offline, skip per-pin fallback"
            )
            return self.helpers.default_offline_snapshot()

        # Fallback for non-bulk pins
        for pin_name, pin_cfg in self.register_map.items():
            if not pin_cfg.get("readable"):
                continue
            if pin_name in result:
                continue

            try:
                result[pin_name] = await self.read_value(pin_name)
            except Exception as exc:
                self.logger.warning(f"[{self.model}:{self.slave_id}] Fallback read failed: {pin_name}: {exc}; set -1")
                result[pin_name] = DEFAULT_MISSING_VALUE

        result = self.computed_processor.compute(result)
        return result

    async def read_value(self, name: str) -> float | int:
        """Read a single parameter value."""
        config: dict = self.helpers.require_readable(name)
        if not config:
            return DEFAULT_MISSING_VALUE

        bus: ModbusBus = self.helpers.get_bus_for_pin(name, self.register_type, self._bus_cache)
        pin_register_type: str = config.get("register_type", self.register_type)
        offset: int | str = config.get("offset", "unknown")

        # Handle coil/discrete input
        if pin_register_type == RegisterType.COIL.value:
            return await self._read_coil(name, bus, offset)

        if pin_register_type == RegisterType.DISCRETE_INPUT.value:
            return await self._read_discrete_input(name, bus, offset)

        # Handle holding/input registers
        value: int | float = await self.register_handler.read_raw(config)
        if value == DEFAULT_MISSING_VALUE:
            self.logger.warning(
                f"[{self.model}:{self.slave_id}] "
                f"Parameter '{name}' ({pin_register_type}) read failed (offset={offset})"
            )
            return value

        # Apply transformations (now properly async)
        value: float | int = await self._apply_transformations(config, value, bus)
        return value

    async def write_value(self, name: str, value: int | float):
        """
        Write a value to a parameter.

        Supports:
        - Bit-level RMW for holding registers
        - Direct coil write (FC 05)
        - Full-word write for holding registers
        """
        pin_config: dict = self.helpers.require_writable(name)
        if not pin_config:
            raise ValueError(f"Pin '{name}' is not writable in register_map")

        if not self.constraints.allow(name, float(value)):
            return

        bus: ModbusBus = self.helpers.get_bus_for_pin(name, self.register_type, self._bus_cache)
        pin_register_type: str = pin_config.get("register_type", self.register_type)

        # Handle coil write
        if pin_register_type == RegisterType.COIL.value:
            await self._write_coil(name, bus, pin_config, value)
            return

        # Handle bit write
        bit_index = pin_config.get("bit")
        if bit_index is not None:
            await self._write_bit_operation(name, pin_config, int(bit_index), int(value))
            return

        # Handle full-word write
        raw = self.helpers.scaled_raw_value(pin_config, value)
        await self.register_handler.write_word(pin_config["offset"], raw)
        self.hooks.on_write(name, pin_config)
        self.logger.info(f"[{self.model}] Write {raw} to {name} (offset={pin_config['offset']})")

    async def write_on_off(self, value: int) -> None:
        """
        Legacy method for writing on/off state.
        Prefer using turn_on()/turn_off() from base class.
        """
        cfg = self.register_map.get(REG_RW_ON_OFF)
        if not cfg or not cfg.get("writable"):
            self.logger.error(f"[{self.model}] {REG_RW_ON_OFF} is not writable or not defined, skip write_on_off")
            return
        await self.write_value(REG_RW_ON_OFF, int(value))

    # ==================== Internal helper methods ====================

    async def _get_or_create_bus(self, register_type: str) -> ModbusBus:
        """Get or create ModbusBus for a specific register type."""
        if register_type in self._bus_cache:
            return self._bus_cache[register_type]

        bus_slave_id = (
            int(self.slave_id) if isinstance(self.slave_id, str) and self.slave_id.isdigit() else int(self.slave_id)
        )

        new_bus = ModbusBus(
            client=self.client,
            slave_id=bus_slave_id,
            register_type=register_type,
            lock=self._port_lock,
        )
        self._bus_cache[register_type] = new_bus
        return new_bus

    async def _read_coil(self, name: str, bus: ModbusBus, offset: int) -> int:
        """Read coil value (FC 01)."""
        try:
            raw_value: int = await bus.read_coil(offset)
            if raw_value == DEFAULT_MISSING_VALUE:
                self.logger.warning(
                    f"[{self.model}:{self.slave_id}] Parameter '{name}' (coil) read failed (offset={offset})"
                )
                return DEFAULT_MISSING_VALUE
            return 1 if raw_value else 0
        except Exception as e:
            self.logger.warning(
                f"[{self.model}:{self.slave_id}] Parameter '{name}' (coil) read failed (offset={offset}) - {e}"
            )
            return DEFAULT_MISSING_VALUE

    async def _read_discrete_input(self, name: str, bus: ModbusBus, offset: int) -> int:
        """Read discrete input value (FC 02)."""
        try:
            raw_value: int = await bus.read_discrete_input(offset)
            if raw_value == DEFAULT_MISSING_VALUE:
                self.logger.warning(
                    f"[{self.model}:{self.slave_id}] Parameter '{name}' (discrete_input) read failed (offset={offset})"
                )
                return DEFAULT_MISSING_VALUE
            return 1 if raw_value else 0
        except Exception as e:
            self.logger.warning(
                f"[{self.model}:{self.slave_id}] Parameter '{name}' (discrete_input) read failed (offset={offset}) - {e}"
            )
            return DEFAULT_MISSING_VALUE

    async def _write_coil(self, name: str, bus: ModbusBus, pin_config: dict, value: int | float):
        """Write coil value (FC 05)."""
        bool_value = bool(value != 0)
        try:
            await bus.write_coil(pin_config["offset"], bool_value)
            self.logger.info(
                f"[{self.model}_{self.slave_id}] Write coil {name} (offset={pin_config['offset']}) = {bool_value}"
            )
        except Exception as e:
            self.logger.error(f"[{self.model}_{self.slave_id}] Failed to write coil {name}: {e}")
            raise

    async def _write_bit_operation(self, name: str, pin_cfg: dict, bit_index: int, bit_value: int):
        """Perform bit-level write using read-modify-write."""
        new_word = await self.register_handler.write_bit(pin_cfg["offset"], bit_index, bit_value)

        if new_word is not None:
            self.hooks.on_write(name, pin_cfg)
            self.logger.info(
                f"[{self.model}] WriteBit {bit_value} to {name}[bit={bit_index}] (offset={pin_cfg['offset']})"
            )

    async def _apply_transformations(self, config: dict, value: int | float, bus: ModbusBus) -> int | float:
        """Apply all transformations to a raw value."""

        # Bit extraction
        if config.get("bit") is not None:
            value = self.decoder.extract_bit(value, config["bit"])

        # Linear formula
        if config.get("formula") is not None:
            value = self.decoder.apply_linear_formula(value, config["formula"])

        # Constant scale
        scale_value = config.get("scale")
        if scale_value is not None:
            value = self.decoder.apply_scale(value, scale_value)

        # Dynamic scale
        scale_from = config.get("scale_from")
        if scale_from is not None:
            factor = await self.helpers.resolve_dynamic_scale(scale_from, bus)
            value = self.decoder.apply_scale(value, factor)

        # Value precision
        precision = config.get("precision")
        if precision is not None:
            value = round(value, precision)

        return value
