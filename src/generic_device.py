import logging
from typing import Any

from pymodbus.client import AsyncModbusSerialClient
from pymodbus.exceptions import ModbusException

from util.decode_util import NumericFormat, decode_numeric_by_format


class AsyncGenericModbusDevice:
    def __init__(
        self,
        model: str,
        client: AsyncModbusSerialClient,
        slave_id: int,
        register_type: str,
        register_map: dict,
        device_type: str,
        constraints: dict = None,
        tables: dict | None = None,
        modes: dict | None = None,
        write_hooks: list | None = None,
    ):
        self.model = model
        self.client = client
        self.slave_id = slave_id  # TODO: Need to determine if slave_id should be str or int
        self.register_type = register_type

        # Allow tables/modes to be placed at the same level as register_map.
        # Pop them out here first to prevent read_all() from treating them as pins.
        self.tables = tables if tables is not None else register_map.pop("tables", {})
        self.modes = modes if modes is not None else register_map.pop("modes", {})

        self.register_map = register_map
        self.logger = logging.getLogger(f"Device.{self.model}")
        self.device_type = device_type
        self.constraints = constraints or {}

        # list of writable pins (for convenience only).
        self.output_register_map = [k for k, v in register_map.items() if v.get("writable")]

        # Simple scale cache (currently optional; field reserved for potential future write_hooks fallback).
        self._scale_cache: dict[str, float] = {}
        self.write_hooks = write_hooks or register_map.pop("write_hooks", [])

    @property
    def pin_type_map(self) -> dict[str, str]:
        """
        Converts pins with a defined 'type' in the register_map to their corresponding
        unified sensor type.
        Pins without a defined 'type' will not appear in the result.
        """
        type_mapping = {
            "thermometer": "Temp",
            "pressure": "Pressure",
            # Extendable mapping for more driver-defined types
        }

        return {
            pin: type_mapping[cfg["type"]]
            for pin, cfg in self.register_map.items()
            if "type" in cfg and cfg["type"] in type_mapping
        }

    async def read_all(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, config in self.register_map.items():
            if not config.get("readable", False):
                continue
            try:
                value = await self._read_value(name, config)
                result[name] = value
            except Exception as e:
                self.logger.warning(f"Failed to read {name}: {e}")
        return result

    async def read_value(self, name: str) -> float | int:
        config: dict = self.register_map.get(name)
        if not config or not config.get("readable"):
            raise ValueError(f"[{self.model}] register_map {name} is not readable")
        return await self._read_value(name, config)

    async def write_value(self, name: str, value: int | float):
        cfg: dict = self._validate_writable(name)

        if not self._validate_constraints(name, value):
            return

        raw: int = self._scale_to_raw(value, cfg.get("scale", 1.0))

        await self._write_register(cfg["offset"], raw)
        self.logger.info(f"[{self.model}] Write {value} ({raw}) to {name} (offset={cfg['offset']})")

        try:
            self._handle_write_hooks(name, cfg)
        except Exception as e:
            self.logger.warning(f"[{self.model}] write_hooks handling failed for {name}: {e}")

    def supports_on_off(self) -> bool:
        """
        Determine whether the device supports RW_ON_OFF:
          - inverter/vfd types → True
          - others (AI, DI, IO module, flow meter, ...) → False
          - if register_map explicitly defines RW_ON_OFF with writable=True,
            it is also considered supported
        """
        cfg: dict = self.register_map.get("RW_ON_OFF")
        if cfg and cfg.get("writable", False):
            return True

        # Decide according to device_type
        onoff_supported_types = {"inverter", "vfd", "inverter_vfd"}
        return self.device_type in onoff_supported_types

    async def _read_value(self, name: str, config: dict) -> float | int:
        # 1) Get raw value (single word / two words / composed words)
        if config.get("composed_of"):
            result = await self._read_composed_value(config)
        elif config.get("combine_high") is not None:
            result = await self._read_combined_registers(config)  # your original 2x16 legacy path
        else:
            result = await self._read_formatted_register(config)

        # 2) Bitmask
        if config.get("bit") is not None:
            result = self._apply_bitmask(result, config["bit"])

        # 3) Linear formula (compatible with legacy n1, n2, n3)
        if config.get("formula"):
            result = self._apply_formula(result, config["formula"])

        # 4) Apply constant scale first
        result = self._apply_scale(result, config.get("scale", 1.0))

        # 5) Then apply dynamic scale_from
        sf = config.get("scale_from")
        if sf:
            if sf == "current_index":
                result *= await self._get_scale_current()
            elif sf == "voltage_index":
                result *= await self._get_scale_voltage()
            elif sf == "energy_index":
                result *= await self._get_scale_energy_auto()
            elif sf == "kwh_scale":
                result *= await self._get_scale_kwh()
            else:
                self.logger.warning(f"[{self.model}] Unknown scale_from '{sf}' for {name}")

        return result

    async def _read_register(self, address: int) -> int:
        result = await self._read_registers(address, 1)
        return result[0]

    async def _read_registers(self, address: int, count: int) -> list[int]:
        if not self.client.connected:
            connected: bool = await self.client.connect()
            if not connected:
                raise ModbusException(f"Failed to connect [{self.client}]")

        if self.register_type == "holding":
            resp = await self.client.read_holding_registers(address=address, count=count, slave=self.slave_id)
        elif self.register_type == "input":
            resp = await self.client.read_input_registers(address=address, count=count, slave=self.slave_id)
        else:
            raise ValueError(f"Unsupported register type: {self.register_type}")

        if resp.isError():
            raise ModbusException(f"Read error: {resp}")

        return resp.registers

    async def _write_register(self, address: int, value: int):
        self.logger.info(f"[{self.model}] Write raw value {value} to offset {address}")
        await self.client.write_register(address=address, value=value, slave=self.slave_id)

    async def write_on_off(self, value: int):
        """Control the on/off state of the device."""

        reg_name = "RW_ON_OFF"  # TODO: Use Enum or constant for register name
        cfg: dict = self.register_map.get(reg_name)

        if not cfg or not cfg.get("writable"):
            raise ValueError(f"[{self.model}] {reg_name} is not writable or not defined")

        await self.write_value(reg_name, value)
        self.logger.info(f"[{self.model}] Write {value} to {reg_name} (offset={cfg['offset']})")

    async def _read_combined_registers(self, config: dict) -> float:
        """
        Legacy 2x16 merge logic (low/high).
        """
        low: int = await self._read_register(config["offset"])
        high: int = await self._read_register(config["combine_high"])
        combined: int = (high << 16) + low
        return combined / config.get("combine_scale", 1.0)

    async def _read_formatted_register(self, config: dict) -> float | int:
        """
        Single-pin read (supports i16/u16).
        If the format is UINT32/FLOAT32 etc., fall back to decode_numeric_by_format.
        """
        fmt = config.get("format", "u16")

        # Added i16 / u16 (fast path)
        if isinstance(fmt, str):
            f = fmt.lower()
            if f in ("u16", "uint16"):
                raw = await self._read_register(config["offset"])
                return int(raw)
            if f in ("i16", "int16"):
                raw = await self._read_register(config["offset"])
                return self._decode_i16(raw)
            if f in ("u32", "uint32", "f32", "float32"):
                count = 2
                raw_list: list[int] = await self._read_registers(config["offset"], count)
                # Try using util.decode; if util only accepts NumericFormat, then convert
                nf = self._to_numeric_format(f)
                if nf is not None:
                    return decode_numeric_by_format(raw_list, nf)
                return decode_numeric_by_format(raw_list, fmt)  # If util supports string, also fine

        # For others, follow legacy path: decide register count by NumericFormat, then decode
        count = 2 if config.get("format", "uint16") in {NumericFormat.FLOAT32, NumericFormat.UINT32} else 1
        raw: list[int] = await self._read_registers(config["offset"], count)
        return decode_numeric_by_format(raw, config.get("format", "uint16"))

    async def _read_composed_value(self, config: dict) -> int:
        """
        Support for composed_of + compose_format.
        Currently supports compose_format: u48_be (HI|MD|LO → 48-bit unsigned).
        """
        names: list[str] = config.get("composed_of", [])
        if not names or len(names) != 3:
            raise ValueError(f"[{self.model}] composed_of must have exactly 3 names for u48_be")

        # Lookup by name, directly read raw u16 (without applying format/scale)
        words: list[int] = []
        for n in names:
            pin_cfg = self.register_map.get(n)
            if not pin_cfg or "offset" not in pin_cfg:
                raise ValueError(f"[{self.model}] composed_of pin '{n}' not defined or missing offset")
            w = await self._read_register(pin_cfg["offset"])
            words.append(int(w) & 0xFFFF)

        compose_fmt = (config.get("compose_format") or "").lower()
        if compose_fmt != "u48_be":
            raise ValueError(f"[{self.model}] compose_format '{compose_fmt}' not supported (expect u48_be)")

        hi, md, lo = words  # BE: w1=HI, w2=MD, w3=LO
        val = (hi << 32) | (md << 16) | lo
        return val  # Treat energy as unsigned

    # -----------------------------
    # Internal: scaling (with out-of-range fallback)
    # -----------------------------
    async def _get_scale_current(self) -> float:
        if "current" in self._scale_cache:
            return self._scale_cache["current"]

        idx = await self._safe_read_index("SCALE_CurrentIndex")
        table: list[float] = self._get_table("current_table")
        val = self._table_pick(table, idx, default=0.01, table_name="current_table")
        self._scale_cache["current"] = val
        return val

    async def _get_scale_voltage(self) -> float:
        if "voltage" in self._scale_cache:
            return self._scale_cache["voltage"]

        idx = await self._safe_read_index("SCALE_VoltageIndex")
        table: list[float] = self._get_table("voltage_table")
        val = self._table_pick(table, idx, default=1.0, table_name="voltage_table")
        self._scale_cache["voltage"] = val
        return val

    async def _get_scale_energy_auto(self) -> float:
        if "energy_auto" in self._scale_cache:
            return self._scale_cache["energy_auto"]

        idx = await self._safe_read_index("SCALE_EnergyIndex")
        base_table: list[float] = self._get_table("energy_table")
        base = self._table_pick(base_table, idx, default=1.0, table_name="energy_table")
        post = float(self.tables.get("energy_post_multiplier", 0.001))
        val = base * post
        self._scale_cache["energy_auto"] = val
        return val

    async def _get_scale_kwh(self) -> float:
        """
        KWh-specific scaling:
        - modes.kwh.mode == "fixed" → return fixed_scale (default 0.01)
        - others (or not set) → same as energy_auto
        """
        if "kwh" in self._scale_cache:
            return self._scale_cache["kwh"]

        kwh_mode_cfg = self.modes.get("kwh", {}) if isinstance(self.modes, dict) else {}
        mode = (kwh_mode_cfg.get("mode") or "auto").lower()
        if mode == "fixed":
            val = float(kwh_mode_cfg.get("fixed_scale", 0.01))
        else:
            val = await self._get_scale_energy_auto()

        self._scale_cache["kwh"] = val
        return val

    async def _safe_read_index(self, name: str) -> int:
        """
        Read index register; if undefined or read fails, return -1 to trigger fallback.
        """
        pin = self.register_map.get(name)
        if not pin or "offset" not in pin:
            self.logger.warning(f"[{self.model}] index register '{name}' not defined; using fallback")
            return -1
        try:
            raw = await self._read_register(pin["offset"])
            return int(raw)
        except Exception as e:
            self.logger.warning(f"[{self.model}] read index '{name}' failed: {e}; using fallback")
            return -1

    def _get_table(self, name: str) -> list[float]:
        tbl = self.tables.get(name, [])
        if not isinstance(tbl, list):
            self.logger.warning(f"[{self.model}] table '{name}' invalid; using empty list")
            return []
        return tbl

    def _table_pick(self, table: list[float], idx: int, default: float, table_name: str) -> float:
        if 0 <= idx < len(table):
            try:
                return float(table[idx])
            except Exception:
                self.logger.warning(f"[{self.model}] table '{table_name}'[{idx}] not float; using default {default}")
        else:
            self.logger.warning(
                f"[{self.model}] table '{table_name}' index {idx} out of range; using default {default}"
            )
        return float(default)

    def _validate_writable(self, name: str) -> dict:
        cfg: dict = self.register_map.get(name)
        if not cfg or not cfg.get("writable"):
            raise ValueError(f"[{self.model}] register_map {name} is not writable")
        return cfg

    def _validate_constraints(self, name: str, value: int | float) -> bool:
        if name in self.constraints:
            limit = self.constraints[name]
            min_val = limit.get("min", 60.0)
            max_val = limit.get("max", 60.0)
            if not min_val <= value <= max_val:
                self.logger.warning(f"[{self.model}] Reject write: {name}={value} out of range [{min_val}, {max_val}]")
                return False
        return True

    @staticmethod
    def _scale_to_raw(value: int | float, scale: float) -> int:
        return int(round(value / scale))

    @staticmethod
    def _apply_bitmask(value: float | int, bit: int) -> int:
        return (int(value) >> bit) & 1

    @staticmethod
    def _apply_formula(value: float | int, formula: tuple) -> float:
        n1, n2, n3 = formula
        return (value + n1) * n2 + n3

    @staticmethod
    def _apply_scale(value: float | int, scale: float) -> float:
        return value * scale

    @staticmethod
    def _decode_i16(raw: int) -> int:
        raw = int(raw) & 0xFFFF
        return raw - 0x10000 if raw & 0x8000 else raw

    @staticmethod
    def _to_numeric_format(fmt_str: str):
        """
        Map the given string to a NumericFormat in util.decode_util.
        Returns None if no matching format is found.
        """
        f = (fmt_str or "").lower()
        try:
            if f in ("u32", "uint32"):
                return NumericFormat.UINT32
            if f in ("f32", "float32"):
                return NumericFormat.FLOAT32
        except Exception:
            pass
        return None

    def _invalidate_scales(self, keys: list[str] | None = None):
        # NOTE: Invalidate scale cache (if no keys are given, clear all)
        if not keys:
            self._scale_cache.clear()
            self.logger.debug(f"[{self.model}] scale cache invalidated (all)")
            return
        for k in keys:
            self._scale_cache.pop(k, None)
        self.logger.debug(f"[{self.model}] scale cache invalidated (keys={keys})")

    def _handle_write_hooks(self, pin_name: str, cfg: dict):
        # NOTE: Decide whether to invalidate cache based on YAML write_hooks
        """
        Supports 3 configuration styles:
        1) String list: ["CFG_PT_1st", ...]
           → If matched, clear all scale cache
        2) Object:
           - registers: [pinName...]
           - offsets:   [34, 35, ...]      (optional)
           - invalidate:[ "scales.current","scales.energy_auto","scales.kwh","scales.voltage" ]
                        (optional; if not provided, clear all)
        3) If the whole hooks is a dict, treat it as a single object
        """
        hooks = self.write_hooks or []
        if isinstance(hooks, dict):
            hooks = [hooks]

        for h in hooks:
            # 1) Simple string
            if isinstance(h, str):
                if h == pin_name:
                    self._invalidate_scales()
                    return
                continue

            # 2) Object
            if not isinstance(h, dict):
                continue

            regs = h.get("registers", [])
            offs = h.get("offsets", [])
            hit = False
            if pin_name in regs:
                hit = True
            elif offs and ("offset" in cfg) and (cfg["offset"] in offs):
                hit = True

            if not hit:
                continue

            inv = h.get("invalidate")
            if inv:
                # "scales.current" → "current"
                keys = []
                for item in inv:
                    if isinstance(item, str) and item.startswith("scales."):
                        keys.append(item.split(".", 1)[1])
                self._invalidate_scales(keys if keys else None)
            else:
                self._invalidate_scales()
            return
