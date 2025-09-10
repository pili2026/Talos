import logging
from typing import Any

from device.generic.capability import supports_on_off
from device.generic.constraints_policy import ConstraintPolicy
from device.generic.hooks import HookManager
from device.generic.modbus_bus import ModbusBus
from device.generic.scales import ScaleService
from device.generic.value_codecs import ValueDecoder
from model.device_constant import (
    DEFAULT_MISSING_VALUE,
    HI_SHIFT,
    MD_SHIFT,
    REG_RW_ON_OFF,
)
from util.decode_util import NumericFormat


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
        # 1) First check connectivity: if not connected → return an offline snapshot immediately
        if not await self.bus.ensure_connected():
            self.logger.warning("[OFFLINE] bus not connected; return default -1 snapshot")
            return self._default_offline_snapshot()

        # 2) If connected → read normally; if a single read fails → set that field to -1
        result: dict[str, Any] = {}
        for name, cfg in self.register_map.items():
            if not cfg.get("readable"):
                continue
            try:
                result[name] = await self.read_value(name)
            except Exception as e:
                self.logger.warning(f"Failed to read {name}: {e}; set -1")
                result[name] = DEFAULT_MISSING_VALUE

        return result

    async def read_value(self, name: str) -> float | int:
        config: dict = self._require_readable(name)
        if not config:
            return DEFAULT_MISSING_VALUE

        # 1) raw
        value: int | float = await self._read_raw(config)
        if value == DEFAULT_MISSING_VALUE:
            return value

        # 2) bit
        if config.get("bit") is not None:
            value = self.decoder.apply_bit(value, config["bit"])

        # 3) linear formula
        if config.get("formula"):
            value = self.decoder.apply_formula(value, config["formula"])

        # 4) constant scale
        value = self.decoder.apply_scale(value, config.get("scale", 1.0))

        # 5) dynamic scale
        scale_from: str = config.get("scale_from")
        if scale_from:
            factor = await self._resolve_dynamic_scale(scale_from)
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

    async def write_on_off(self, value: int) -> None:
        cfg = self.register_map.get(REG_RW_ON_OFF)
        if not cfg or not cfg.get("writable"):
            self.logger.error(f"[{self.model}] {REG_RW_ON_OFF} is not writable or not defined, skip write_on_off")
            return
        await self.write_value(REG_RW_ON_OFF, int(value))

    # -----------------
    # internal helpers
    # -----------------
    async def _read_raw(self, reg_config: dict) -> float | int:
        if not await self.bus.ensure_connected():
            self.logger.warning("[OFFLINE] bus not connected; return -1 for raw read")
            return DEFAULT_MISSING_VALUE

        # composed 48-bit (HI|MD|LO)
        if reg_config.get("composed_of"):
            # TODO: Need to clarify the format of composed_of
            sub_registers: list | tuple = reg_config["composed_of"]
            if not isinstance(sub_registers, (list, tuple)) or len(sub_registers) != 3:
                self.logger.error(f"[{self.model}] Invalid composed_of={sub_registers}, must have exactly 3 entries")
                return DEFAULT_MISSING_VALUE  # fallback value

            register_value_list: list[int] = []
            for sub_register in sub_registers:
                pin_cfg = self.register_map.get(sub_register) or {}
                if "offset" not in pin_cfg:
                    return DEFAULT_MISSING_VALUE

                register_value_list.append(await self.bus.read_u16(pin_cfg["offset"]))
            hi, md, lo = [int(w) & 0xFFFF for w in register_value_list]
            return (hi << HI_SHIFT) | (md << MD_SHIFT) | lo

        # normal path: choose register count by format
        fmt = reg_config.get("format", NumericFormat.U16)
        requires_two_words: bool = str(fmt).lower() in {
            NumericFormat.U32,
            NumericFormat.UINT32,
            NumericFormat.F32,
            NumericFormat.FLOAT32,
        } or fmt in {
            NumericFormat.UINT32,
            NumericFormat.FLOAT32,
        }
        word_count = 2 if requires_two_words else 1
        register_value_list = await self.bus.read_regs(reg_config["offset"], word_count)
        return self.decoder.decode_words(fmt, register_value_list)

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
