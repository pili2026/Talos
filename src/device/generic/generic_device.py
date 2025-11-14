import logging
from typing import Any

from pymodbus.client import AsyncModbusSerialClient

from device.generic.computed_field_processor import ComputedFieldProcessor
from device.generic.constraints_policy import ConstraintPolicy
from device.generic.hooks import HookManager
from device.generic.modbus_bus import ModbusBus
from device.generic.scales import ScaleService
from model.device_constant import DEFAULT_MISSING_VALUE, HI_SHIFT, MD_SHIFT, REG_RW_ON_OFF
from util.data_decoder import DecodeFormat
from util.value_decoder import ValueDecoder


class AsyncGenericModbusDevice:
    def __init__(
        self,
        model: str,
        client: AsyncModbusSerialClient,
        slave_id: int | str,
        register_type: str,
        register_map: dict,
        device_type: str,
        constraint_policy: ConstraintPolicy | None = None,
        table_dict: dict | None = None,
        mode_dict: dict | None = None,
        write_hooks: list | dict | None = None,
    ):
        self.model = model
        self.logger = logging.getLogger(f"Device.{self.model}")
        self.register_map = register_map
        self.device_type = device_type

        self.client = client
        self.register_type = register_type
        self.slave_id = slave_id

        # normalize slave_id to int for bus
        slave_id = (
            int(self.slave_id) if isinstance(self.slave_id, str) and self.slave_id.isdigit() else int(self.slave_id)
        )
        self.bus = ModbusBus(client=client, slave_id=slave_id, register_type=register_type)

        # Create bus cache for different register types
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
        """Read all readable pins."""
        # 1) First check connectivity using default bus
        if not await self.bus.ensure_connected():
            self.logger.warning("[OFFLINE] default bus not connected; return default -1 snapshot")
            return self._default_offline_snapshot()

        # 2) If connected, read all pins
        # Note: Each pin may use a different bus (different register_type)
        result: dict[str, Any] = {}
        for name, cfg in self.register_map.items():
            if not cfg.get("readable"):
                continue
            try:
                result[name] = await self.read_value(name)
            except Exception as e:
                self.logger.warning(f"Failed to read {name}: {e}; set -1")
                result[name] = DEFAULT_MISSING_VALUE

        # 3) Process computed fields (if any)
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
        if pin_register_type == "coil":
            # Read Coil (FC 01)
            try:
                raw_bool = await bus.read_coil(offset)
                value = 1 if raw_bool else 0
            except Exception as e:
                self.logger.warning(
                    f"[{self.model}:{self.slave_id}] " f"Parameter '{name}' (coil) read failed (offset={offset}) - {e}"
                )
                return DEFAULT_MISSING_VALUE

        elif pin_register_type == "discrete_input":
            # Read Discrete Input (FC 02)
            try:
                raw_bool: bool = await bus.read_discrete_input(offset)
                value = 1 if raw_bool else 0
            except Exception as e:
                self.logger.warning(
                    f"[{self.model}:{self.slave_id}] "
                    f"Parameter '{name}' (discrete_input) read failed (offset={offset}) - {e}"
                )
                return DEFAULT_MISSING_VALUE

        else:
            # Original holding/input register logic
            value: int | float = await self._read_raw(config)

            # Record holding/input register read failure
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

        if pin_register_type == "coil":
            # Write Single Coil (FC 05)
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

        # Whole-word / analog path
        raw = self._scaled_raw_value(pin_config, value)
        await self._write_word(name, pin_config, raw)

    async def write_on_off(self, value: int) -> None:
        cfg = self.register_map.get(REG_RW_ON_OFF)
        if not cfg or not cfg.get("writable"):
            self.logger.error(f"[{self.model}] {REG_RW_ON_OFF} is not writable or not defined, skip write_on_off")
            return
        await self.write_value(REG_RW_ON_OFF, int(value))

    # -----------------
    # internal helpers
    # -----------------

    async def _write_word(self, name: str, pin_cfg: dict, raw_value: int) -> None:
        """Write a full 16-bit word."""
        await self.bus.write_u16(pin_cfg["offset"], int(raw_value))
        self.hooks.on_write(name, pin_cfg)
        self.logger.info(f"[{self.model}] Write {raw_value} to {name} (offset={pin_cfg['offset']})")

    async def _write_bit(self, name: str, pin_cfg: dict, bit_index: int, bit_value: int) -> None:
        """Read-modify-write a single bit within a 16-bit register."""
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

    # replace your method with this version
    async def _read_raw(self, reg_config: dict) -> float | int:
        """
        Read raw value(s) from Modbus according to the register configuration.
        - Supports 48-bit composed values via `composed_of` (HI|MD|LO words).
        - Chooses word count by format (u16/i16 → 1 word; u32/f32 → 2 words).
        """
        if not await self.bus.ensure_connected():
            self.logger.warning("[OFFLINE] bus not connected; return -1 for raw read")
            return DEFAULT_MISSING_VALUE

        # --- 48-bit composed path: composed_of = [hi_key, md_key, lo_key] ---
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
                # Each part is a single 16-bit word
                word = await self.bus.read_u16(pin_cfg["offset"])
                register_value_list.append(int(word) & 0xFFFF)

            # Expect order: HI | MD | LO
            hi, md, lo = register_value_list
            return (hi << HI_SHIFT) | (md << MD_SHIFT) | lo

        # --- normal path: determine word count by format ---
        fmt = reg_config.get("format", DecodeFormat.U16)
        word_count: int = AsyncGenericModbusDevice._required_word_count(fmt)

        try:
            registers = await self.bus.read_regs(reg_config["offset"], word_count)
            # Safety: ensure we got enough words
            if not isinstance(registers, (list, tuple)) or len(registers) < word_count:
                self.logger.error(f"[{self.model}] read_regs returned insufficient words for {fmt}: {registers}")
                return DEFAULT_MISSING_VALUE
        except Exception as e:
            self.logger.exception(
                f"[{self.model}] read_regs failed at offset={reg_config.get('offset')} fmt={fmt}: {e}"
            )
            return DEFAULT_MISSING_VALUE

        # Decode using the high-level decoder (supports u32_le/u32_be/f32_le/f32_be/etc.)
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
        # All readable fields → -1
        snap: dict[str, float | int] = {
            name: DEFAULT_MISSING_VALUE for name, cfg in self.register_map.items() if cfg.get("readable")
        }
        return snap

    def _scaled_raw_value(self, pin_cfg: dict, value: int | float) -> int:
        """Apply static scale and cast to int word."""
        scale = float(pin_cfg.get("scale", 1.0))
        return int(round(float(value) / scale))

    def _get_bus_for_pin(self, pin_name: str) -> ModbusBus:
        """
        Get the ModbusBus instance for a specific pin.

        If the pin has a 'register_type' attribute, use that to select the bus.
        Otherwise, use the default register_type.

        Lazily creates bus instances as needed and caches them.

        Args:
            pin_name: Name of the pin

        Returns:
            ModbusBus instance for the pin's register_type
        """
        pin_def: dict = self.register_map.get(pin_name)
        if not pin_def:
            # Pin not found, return default bus
            return self.bus

        # Get pin-level register_type (if specified)
        pin_register_type: str = pin_def.get("register_type", self.register_type)

        # Return cached bus if exists
        if pin_register_type in self._bus_cache:
            return self._bus_cache[pin_register_type]

        # Create new bus for this register_type
        slave_id = (
            int(self.slave_id) if isinstance(self.slave_id, str) and self.slave_id.isdigit() else int(self.slave_id)
        )

        new_bus = ModbusBus(self.client, slave_id, pin_register_type)
        self._bus_cache[pin_register_type] = new_bus

        self.logger.info(
            f"[{self.model}_{self.slave_id}] Created ModbusBus for pin '{pin_name}' "
            f"with register_type='{pin_register_type}'"
        )

        return new_bus

    @staticmethod
    def _required_word_count(fmt: str | DecodeFormat) -> int:
        """
        Return number of 16-bit Modbus registers required for the given data format.
        - 1 word: u16 / i16
        - 2 words: u32 (le/be), f32 (le/be/swap variants)
        """
        # Normalize to enum
        if isinstance(fmt, str):
            try:
                fmt = DecodeFormat(fmt.lower())
            except ValueError:
                return 1  # Unknown format, assume 1 word

        # Match-case for word count
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
