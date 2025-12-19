import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from pymodbus.client import AsyncModbusSerialClient

from core.device.generic.computed_field_processor import ComputedFieldProcessor
from core.device.generic.constraints_policy import ConstraintPolicy
from core.device.generic.hooks import HookManager
from core.device.generic.modbus_bus import ModbusBus
from core.device.generic.scales import ScaleService
from core.model.device_constant import DEFAULT_MISSING_VALUE, HI_SHIFT, MD_SHIFT, REG_RW_ON_OFF
from core.model.enum.register_type_enum import RegisterType
from core.util.data_decoder import DecodeFormat
from core.util.value_decoder import ValueDecoder


@dataclass(frozen=True)
class BulkRange:
    register_type: str
    start: int
    count: int
    items: list[tuple[str, dict]]  # (pin_name, cfg)


class AsyncGenericModbusDevice:
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
        self.model = model
        self.logger = logging.getLogger(f"Device.{self.model}")
        self.register_map = register_map
        self.device_type = device_type

        self.client = client
        self.register_type = register_type
        self.slave_id = slave_id

        # store port identity so monitor can reliably find lock without "guessing"
        self.port = str(port)

        # shared per-port lock injected by DeviceManager
        self._port_lock = port_lock

        # normalize slave_id to int for bus
        bus_slave_id = (
            int(self.slave_id) if isinstance(self.slave_id, str) and self.slave_id.isdigit() else int(self.slave_id)
        )
        self.bus = ModbusBus(client=client, slave_id=bus_slave_id, register_type=register_type, lock=self._port_lock)

        # This allows pins to override register_type at pin-level
        self._bus_cache: dict[str, ModbusBus] = {register_type: self.bus}  # default bus

        self.logger.debug(f"[{self.model}_{self.slave_id}] Initialized with default register_type='{register_type}'")

        # allow tables/modes at same level as register_map (backward compat)
        table_dict = table_dict if table_dict is not None else register_map.pop("tables", {})
        mode_dict = mode_dict if mode_dict is not None else register_map.pop("modes", {})

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

        self._model_config = model_config

    @property
    def pin_type_map(self) -> dict[str, str]:
        type_mapping = {"thermometer": "Temp", "pressure": "Pressure"}
        return {
            pin: type_mapping[cfg["type"]]
            for pin, cfg in self.register_map.items()
            if "type" in cfg and cfg["type"] in type_mapping
        }

    def supports_on_off(self) -> bool:
        config = self.register_map.get(REG_RW_ON_OFF)
        if config and config.get("writable"):
            return True
        return str(self.device_type).lower() in {"inverter", "vfd", "inverter_vfd"}

    async def read_all(self) -> dict[str, Any]:
        """
        Bulk read implementation.

        Rules:
        - Only holding/input pins that are bulk-eligible are grouped into contiguous ranges.
        - Each range triggers exactly one Modbus request via ModbusBus.read_regs().
        - If a range read fails, all pins covered by that range return DEFAULT_MISSING_VALUE.
        - Non-bulk-eligible pins fall back to read_value() (coil, discrete_input, composed_of, scale_from, etc.).
        - Computed fields are applied at the end.
        """

        # 1) connectivity check (default bus)
        if not await self.bus.ensure_connected():
            self.logger.warning("[OFFLINE] default bus not connected; return default -1 snapshot")
            return self._default_offline_snapshot()

        result: dict[str, Any] = {}

        # 2) bulk read ranges (holding/input only)
        bulk_ranges = self._build_bulk_ranges(max_regs_per_req=120)

        for bulk_range in bulk_ranges:
            # bulk_range.register_type is expected to be "holding" or "input"
            bus = self._bus_cache.get(bulk_range.register_type)
            if bus is None:
                # Create a bus for this register type (share the same lock)
                bus_slave_id = (
                    int(self.slave_id)
                    if isinstance(self.slave_id, str) and self.slave_id.isdigit()
                    else int(self.slave_id)
                )
                bus = ModbusBus(
                    client=self.client,
                    slave_id=bus_slave_id,
                    register_type=bulk_range.register_type,
                    lock=self._port_lock,
                )
                self._bus_cache[bulk_range.register_type] = bus

            try:
                registers = await bus.read_regs(bulk_range.start, bulk_range.count)
                registers = list(registers)
            except Exception as exc:
                self.logger.warning(
                    f"[{self.model}:{self.slave_id}] Bulk read failed "
                    f"rt={bulk_range.register_type} start={bulk_range.start} count={bulk_range.count}: {exc}"
                )
                for pin_name, _pin_cfg in bulk_range.items:
                    result[pin_name] = DEFAULT_MISSING_VALUE
                continue

            # Map range registers back to pins
            for pin_name, pin_cfg in bulk_range.items:
                try:
                    pin_offset = int(pin_cfg["offset"])
                except Exception:
                    result[pin_name] = DEFAULT_MISSING_VALUE
                    continue

                decode_format = pin_cfg.get("format", DecodeFormat.U16)
                word_count = self._required_word_count(decode_format)

                relative_index = pin_offset - bulk_range.start
                if relative_index < 0:
                    result[pin_name] = DEFAULT_MISSING_VALUE
                    continue

                register_words = registers[relative_index : relative_index + word_count]
                if len(register_words) < word_count:
                    result[pin_name] = DEFAULT_MISSING_VALUE
                    continue

                decoded_value = self.decoder.decode_registers(decode_format, register_words)
                final_value = self._apply_post_process(pin_cfg, decoded_value)
                result[pin_name] = final_value

        # 3) fallback: pins not covered by bulk (coil/discrete_input/composed_of/scale_from/unsupported formats...)
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

        # 4) computed fields
        result = self.computed_processor.compute(result)
        return result

    async def read_value(self, name: str) -> float | int:
        """
        Read a value from a pin.
        Supports:
        - Holding/Input registers (original)
        - Coil (FC 01)
        - Discrete Input (FC 02)
        """
        config: dict = self._require_readable(name)
        if not config:
            return DEFAULT_MISSING_VALUE

        bus: ModbusBus = self._get_bus_for_pin(name)
        pin_register_type: str = config.get("register_type", self.register_type)
        offset: int | str = config.get("offset", "unknown")

        # 1) Read raw value based on register_type
        if pin_register_type == RegisterType.COIL.value:
            try:
                raw_value: int = await bus.read_coil(offset)
                if raw_value == DEFAULT_MISSING_VALUE:
                    self.logger.warning(
                        f"[{self.model}:{self.slave_id}] Parameter '{name}' (coil) read failed (offset={offset})"
                    )
                    return DEFAULT_MISSING_VALUE
                value: int = 1 if raw_value else 0
            except Exception as e:
                self.logger.warning(
                    f"[{self.model}:{self.slave_id}] Parameter '{name}' (coil) read failed (offset={offset}) - {e}"
                )
                return DEFAULT_MISSING_VALUE

        elif pin_register_type == RegisterType.DISCRETE_INPUT.value:
            try:
                raw_value: int = await bus.read_discrete_input(offset)
                if raw_value == DEFAULT_MISSING_VALUE:
                    self.logger.warning(
                        f"[{self.model}:{self.slave_id}] "
                        f"Parameter '{name}' (discrete_input) read failed (offset={offset})"
                    )
                    return DEFAULT_MISSING_VALUE
                value = 1 if raw_value else 0
            except Exception as e:
                self.logger.warning(
                    f"[{self.model}:{self.slave_id}] "
                    f"Parameter '{name}' (discrete_input) read failed (offset={offset}) - {e}"
                )
                return DEFAULT_MISSING_VALUE

        else:
            # holding/input path
            value: int | float = await self._read_raw(config)
            if value == DEFAULT_MISSING_VALUE:
                self.logger.warning(
                    f"[{self.model}:{self.slave_id}] "
                    f"Parameter '{name}' ({pin_register_type}) read failed (offset={offset}) - "
                    f"device may not support this feature"
                )
                return value

        # 2) bit extraction (only for holding/input registers)
        if config.get("bit") is not None:
            value = self.decoder.extract_bit(value, config["bit"])

        # 3) linear formula
        if config.get("formula"):
            value = self.decoder.apply_linear_formula(value, config["formula"])

        # 4) constant scale
        value = self.decoder.apply_scale(value, config.get("scale", 1.0))

        # 5) dynamic scale
        scale_from: str = config.get("scale_from")
        if scale_from:
            factor = await self._resolve_dynamic_scale(scale_from)
            value = self.decoder.apply_scale(value, factor)

        # 6) value precision
        precision: int = config.get("precision")
        if precision:
            value = round(value, config["precision"])

        return value

    async def write_value(self, name: str, value: int | float):
        """
        Write a value to a pin.

        Supports:
        - Bit-level RMW for holding registers
        - Direct coil write (FC 05)
        - Full-word write for holding registers
        """
        pin_config: dict = self._require_writable(name)
        if not pin_config:
            raise ValueError(f"Pin '{name}' is not writable in register_map")

        if not self.constraints.allow(name, float(value)):
            return

        bus: ModbusBus = self._get_bus_for_pin(name)
        pin_register_type: str = pin_config.get("register_type", self.register_type)

        if pin_register_type == RegisterType.COIL.value:
            bool_value = bool(value != 0)
            try:
                await bus.write_coil(pin_config["offset"], bool_value)
                self.logger.info(
                    f"[{self.model}_{self.slave_id}] Write coil {name} (offset={pin_config['offset']}) = {bool_value}"
                )
            except Exception as e:
                self.logger.error(f"[{self.model}_{self.slave_id}] Failed to write coil {name}: {e}")
                raise
            return

        bit_index = pin_config.get("bit")
        if bit_index is not None:
            await self._write_bit(name, pin_config, int(bit_index), int(value))
            return

        raw = self._scaled_raw_value(pin_config, value)
        await self._write_word(name, pin_config, raw)

    async def write_on_off(self, value: int) -> None:
        cfg = self.register_map.get(REG_RW_ON_OFF)
        if not cfg or not cfg.get("writable"):
            self.logger.error(f"[{self.model}] {REG_RW_ON_OFF} is not writable or not defined, skip write_on_off")
            return
        await self.write_value(REG_RW_ON_OFF, int(value))

    def get_health_check_config(self) -> dict | None:
        """
        Get health check configuration from device model definition.

        Returns:
            Health check config dict if defined, None otherwise
        """
        if not isinstance(self._model_config, dict):
            return None

        health_check: dict = self._model_config.get("health_check")

        if health_check and isinstance(health_check, dict):
            return health_check

        return None

    # -----------------
    # internal helpers
    # -----------------

    async def _write_word(self, name: str, pin_cfg: dict, raw_value: int) -> None:
        await self.bus.write_u16(pin_cfg["offset"], int(raw_value))
        self.hooks.on_write(name, pin_cfg)
        self.logger.info(f"[{self.model}] Write {raw_value} to {name} (offset={pin_cfg['offset']})")

    async def _write_bit(self, name: str, pin_cfg: dict, bit_index: int, bit_value: int) -> None:
        try:
            current = await self.bus.read_u16(pin_cfg["offset"])
        except Exception as e:
            self.logger.warning(f"[{self.model}] Read before bit-write failed for {name}: {e}")
            return

        new_word = int(current)
        if bit_value:
            new_word |= 1 << bit_index
        else:
            new_word &= ~(1 << bit_index)

        try:
            await self.bus.write_u16(pin_cfg["offset"], new_word)
            self.hooks.on_write(name, pin_cfg)
            self.logger.info(
                f"[{self.model}] WriteBit {bit_value} to {name}[bit={bit_index}] "
                f"(offset={pin_cfg['offset']}): {current:#06x} -> {new_word:#06x}"
            )
        except Exception as e:
            self.logger.warning(
                f"[{self.model}] Bit-write failed for {name}: {e}. "
                f"WriteBit {bit_value} to {name}[bit={bit_index}] "
                f"(offset={pin_cfg['offset']}): {current:#06x} -> {new_word:#06x}"
            )

    async def _read_raw(self, reg_config: dict) -> float | int:
        """
        Read raw value(s) from Modbus according to the register configuration.
        - Supports 48-bit composed values via `composed_of` (HI|MD|LO words).
        - Chooses word count by format (u16/i16 → 1 word; u32/f32 → 2 words).

        NOTE:
        - Do NOT call ensure_connected() here to avoid connect storms.
        - read_u16/read_regs already perform connect attempts under port lock.
        """

        if reg_config.get("composed_of"):
            sub_registers = reg_config["composed_of"]
            if not isinstance(sub_registers, (list, tuple)) or len(sub_registers) != 3:
                self.logger.error(f"[{self.model}] Invalid composed_of={sub_registers}, must have exactly 3 entries")
                return DEFAULT_MISSING_VALUE

            register_value_list: list[int] = []
            for sub_key in sub_registers:
                pin_cfg = self.register_map.get(sub_key) or {}
                if "offset" not in pin_cfg:
                    self.logger.error(f"[{self.model}] composed_of sub key '{sub_key}' missing 'offset'")
                    return DEFAULT_MISSING_VALUE
                word = await self.bus.read_u16(pin_cfg["offset"])
                register_value_list.append(int(word) & 0xFFFF)

            hi, md, lo = register_value_list
            return (hi << HI_SHIFT) | (md << MD_SHIFT) | lo

        fmt = reg_config.get("format", DecodeFormat.U16)
        word_count: int = AsyncGenericModbusDevice._required_word_count(fmt)

        try:
            registers = await self.bus.read_regs(reg_config["offset"], word_count)
            if not isinstance(registers, (list, tuple)) or len(registers) < word_count:
                self.logger.error(f"[{self.model}] read_regs returned insufficient words for {fmt}: {registers}")
                return DEFAULT_MISSING_VALUE
        except Exception as e:
            self.logger.exception(
                f"[{self.model}] read_regs failed at offset={reg_config.get('offset')} fmt={fmt}: {e}"
            )
            return DEFAULT_MISSING_VALUE

        return self.decoder.decode_registers(fmt, list(registers))

    async def _resolve_dynamic_scale(self, scale_from: str) -> float:
        async def index_reader(index_name: str) -> int:
            pin = self.register_map.get(index_name)
            if not pin:
                self.logger.warning(f"[{self.model}] index '{index_name}' not defined; fallback -1")
                return DEFAULT_MISSING_VALUE
            try:
                return await self.bus.read_u16(pin["offset"])
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

    def _require_readable(self, name: str) -> dict:
        cfg = self.register_map.get(name) or {}
        if not cfg.get("readable"):
            self.logger.warning(f"[{self.model}] register_map {name} is not readable")
            return {}
        return cfg

    def _require_writable(self, name: str) -> dict:
        cfg = self.register_map.get(name) or {}
        if not cfg.get("writable"):
            self.logger.warning(f"[{self.model}] register_map {name} is not writable")
            return {}
        return cfg

    def _default_offline_snapshot(self) -> dict[str, float | int]:
        return {name: DEFAULT_MISSING_VALUE for name, cfg in self.register_map.items() if cfg.get("readable")}

    def _scaled_raw_value(self, pin_cfg: dict, value: int | float) -> int:
        scale = float(pin_cfg.get("scale", 1.0))
        return int(round(float(value) / scale))

    def _get_bus_for_pin(self, pin_name: str) -> ModbusBus:
        pin_def: dict = self.register_map.get(pin_name)
        if not pin_def:
            return self.bus

        pin_register_type: str = pin_def.get("register_type", self.register_type)

        if pin_register_type in self._bus_cache:
            return self._bus_cache[pin_register_type]

        bus_slave_id = (
            int(self.slave_id) if isinstance(self.slave_id, str) and self.slave_id.isdigit() else int(self.slave_id)
        )

        new_bus = ModbusBus(
            client=self.client,
            slave_id=bus_slave_id,
            register_type=pin_register_type,
            lock=self._port_lock,
        )
        self._bus_cache[pin_register_type] = new_bus

        self.logger.info(
            f"[{self.model}_{self.slave_id}] Created ModbusBus for pin '{pin_name}' "
            f"with register_type='{pin_register_type}'"
        )

        return new_bus

    @staticmethod
    def _required_word_count(fmt: str | DecodeFormat) -> int:
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

    def _apply_post_process(self, config: dict, value: int | float) -> int | float:
        # 2) bit extraction (only for holding/input registers)
        if config.get("bit") is not None:
            value = self.decoder.extract_bit(value, config["bit"])

        # 3) linear formula
        if config.get("formula"):
            value = self.decoder.apply_linear_formula(value, config["formula"])

        # 4) constant scale
        value = self.decoder.apply_scale(value, config.get("scale", 1.0))

        # 6) value precision
        precision: int = config.get("precision")
        if precision:
            value = round(value, precision)

        return value

    def _is_bulk_eligible(self, config_raw: dict) -> bool:
        if not config_raw.get("readable"):
            return False
        if config_raw.get("register_type") in {RegisterType.COIL.value, RegisterType.DISCRETE_INPUT.value}:
            return False
        if config_raw.get("composed_of"):
            return False
        if config_raw.get("scale_from"):
            return False
        # holding/input only
        pin_rt = config_raw.get("register_type", self.register_type)
        return pin_rt in {RegisterType.HOLDING.value, RegisterType.INPUT.value, self.register_type}

    def _build_bulk_ranges(self, max_regs_per_req: int = 120) -> list[BulkRange]:
        # (pin_name, pin_cfg, start_offset, word_count, register_type)
        bulk_candidates: list[tuple[str, dict, int, int, str]] = []

        for pin_name, pin_cfg in self.register_map.items():
            if not self._is_bulk_eligible(pin_cfg):
                continue

            register_type = pin_cfg.get("register_type", self.register_type)
            start_offset = int(pin_cfg.get("offset"))
            decode_format = pin_cfg.get("format", DecodeFormat.U16)
            word_count = self._required_word_count(decode_format)

            bulk_candidates.append((pin_name, pin_cfg, start_offset, word_count, register_type))

        # sort by (register_type, start_offset)
        bulk_candidates.sort(key=lambda c: (c[4], c[2]))

        bulk_ranges: list[BulkRange] = []

        current_register_type: str | None = None
        current_range_start: int = 0
        current_range_end: int = 0  # exclusive
        current_range_pins: list[tuple[str, dict]] = []

        for pin_name, pin_cfg, start_offset, word_count, register_type in bulk_candidates:
            next_range_start = start_offset
            next_range_end = start_offset + word_count  # exclusive

            if current_register_type is None:
                current_register_type = register_type
                current_range_start = next_range_start
                current_range_end = next_range_end
                current_range_pins = [(pin_name, pin_cfg)]
                continue

            should_split = (
                register_type != current_register_type
                or next_range_start != current_range_end
                or (next_range_end - current_range_start) > max_regs_per_req
            )

            if should_split:
                bulk_ranges.append(
                    BulkRange(
                        register_type=current_register_type,
                        start=current_range_start,
                        count=current_range_end - current_range_start,
                        items=current_range_pins,
                    )
                )
                current_register_type = register_type
                current_range_start = next_range_start
                current_range_end = next_range_end
                current_range_pins = [(pin_name, pin_cfg)]
                continue

            # merge into current range
            current_range_end = next_range_end
            current_range_pins.append((pin_name, pin_cfg))

        if current_register_type is not None:
            bulk_ranges.append(
                BulkRange(
                    register_type=current_register_type,
                    start=current_range_start,
                    count=current_range_end - current_range_start,
                    items=current_range_pins,
                )
            )

        return bulk_ranges
