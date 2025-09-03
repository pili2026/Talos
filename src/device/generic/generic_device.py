import logging
from typing import Any

from device.generic.capability import supports_on_off
from device.generic.constraints_policy import ConstraintPolicy
from device.generic.hooks import HookManager
from device.generic.modbus_bus import ModbusBus
from device.generic.scales import ScaleService
from device.generic.value_codecs import ValueDecoder
from util.decode_util import NumericFormat

# TODO: Move to model
REG_RW_ON_OFF = "RW_ON_OFF"


class AsyncGenericModbusDevice:
    def __init__(
        self,
        model: str,
        client,
        slave_id: int | str,
        register_type: str,
        register_map: dict,
        device_type: str,
        constraint_dict: dict | None = None,
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
        self.bus = ModbusBus(client, slave_id, register_type)

        # allow tables/modes at same level as register_map (backward compat)
        table_dict = table_dict if table_dict is not None else register_map.pop("tables", {})
        mode_dict = mode_dict if mode_dict is not None else register_map.pop("modes", {})

        self.scales = ScaleService(table_dict=table_dict, mode_dict=mode_dict, logger=self.logger)
        self.constraints = ConstraintPolicy(constraint_dict or {}, self.logger)
        hook_list: list = write_hooks if write_hooks is not None else register_map.pop("write_hooks", [])
        self.hooks = HookManager(hook_list=hook_list, logger=self.logger, scale_service=self.scales)

        self.decoder = ValueDecoder()

    @property
    def pin_type_map(self) -> dict[str, str]:
        type_mapping = {"thermometer": "Temp", "pressure": "Pressure"}
        return {
            pin: type_mapping[cfg["type"]]
            for pin, cfg in self.register_map.items()
            if "type" in cfg and cfg["type"] in type_mapping
        }

    def supports_on_off(self) -> bool:
        # TODO: Refactor this funcion
        return supports_on_off(self.device_type, self.register_map)

    async def read_all(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, cfg in self.register_map.items():
            if not cfg.get("readable"):
                continue
            try:
                result[name] = await self.read_value(name)
            except Exception as e:
                self.logger.warning(f"Failed to read {name}: {e}")
        return result

    async def read_value(self, name: str) -> float | int:
        cfg = self._require_readable(name)
        # 1) raw
        value = await self._read_raw(cfg)

        # 2) bit
        if cfg.get("bit") is not None:
            value = self.decoder.apply_bit(value, cfg["bit"])

        # 3) linear formula
        if cfg.get("formula"):
            value = self.decoder.apply_formula(value, cfg["formula"])

        # 4) constant scale
        value = self.decoder.apply_scale(value, cfg.get("scale", 1.0))

        # 5) dynamic scale
        sf = cfg.get("scale_from")
        if sf:
            factor = await self._resolve_dynamic_scale(sf)
            value = self.decoder.apply_scale(value, factor)
        return value

    async def write_value(self, name: str, value: int | float):
        cfg = self._require_writable(name)
        if not self.constraints.allow(name, float(value)):
            return
        raw = int(round(float(value) / float(cfg.get("scale", 1.0))))
        await self.bus.write_u16(cfg["offset"], raw)
        self.hooks.on_write(name, cfg)
        self.logger.info(f"[{self.model}] Write {value} ({raw}) to {name} (offset={cfg['offset']})")

    async def write_on_off(self, value: int):
        cfg = self.register_map.get(REG_RW_ON_OFF)
        if not cfg or not cfg.get("writable"):
            raise ValueError(f"[{self.model}] {REG_RW_ON_OFF} is not writable or not defined")
        await self.write_value(REG_RW_ON_OFF, int(value))

    # -----------------
    # internal helpers
    # -----------------
    async def _read_raw(self, cfg: dict) -> float | int:
        # composed 48-bit (HI|MD|LO)
        if cfg.get("composed_of"):
            names = cfg["composed_of"]
            if not isinstance(names, (list, tuple)) or len(names) != 3:
                raise ValueError("composed_of must have exactly 3 entries for u48_be")
            words: list[int] = []
            for n in names:
                pin_cfg = self.register_map.get(n) or {}
                words.append(await self.bus.read_u16(pin_cfg["offset"]))
            hi, md, lo = [int(w) & 0xFFFF for w in words]
            return (hi << 32) | (md << 16) | lo

        # normal path: choose register count by format
        fmt = cfg.get("format", "u16")
        needs2 = str(fmt).lower() in {"u32", "uint32", "f32", "float32"} or fmt in {
            NumericFormat.UINT32,
            NumericFormat.FLOAT32,
        }
        count = 2 if needs2 else 1
        words = await self.bus.read_regs(cfg["offset"], count)
        return self.decoder.decode_words(fmt, words)

    async def _resolve_dynamic_scale(self, sf: str) -> float:
        async def index_reader(index_name: str) -> int:
            pin = self.register_map.get(index_name)
            if not pin:
                self.logger.warning(f"[{self.model}] index '{index_name}' not defined; fallback -1")
                return -1
            try:
                return await self.bus.read_u16(pin["offset"])
            except Exception as e:
                self.logger.warning(f"[{self.model}] read index '{index_name}' failed: {e}")
                return -1

        mapping = {
            "current_index": "current",
            "voltage_index": "voltage",
            "energy_index": "energy_auto",
            "kwh_scale": "kwh",
        }
        kind = mapping.get(sf)
        if not kind:
            self.logger.warning(f"[{self.model}] Unknown scale_from '{sf}'")
            return 1.0
        return await self.scales.get_factor(kind, index_reader)

    def _require_readable(self, name: str) -> dict:
        cfg = self.register_map.get(name) or {}
        if not cfg.get("readable"):
            raise ValueError(f"[{self.model}] register_map {name} is not readable")
        return cfg

    def _require_writable(self, name: str) -> dict:
        cfg = self.register_map.get(name) or {}
        if not cfg.get("writable"):
            raise ValueError(f"[{self.model}] register_map {name} is not writable")
        return cfg
