from logging import Logger
from typing import Awaitable, Callable

from core.model.enum.scale_table_enum import ScaleTable


class ScaleService:
    """Responsible for all scale_from and tables/modes, including cache and invalidation."""

    def __init__(self, table_dict: dict, mode_dict: dict, logger: Logger):
        self.table_dict = table_dict or {}
        self.mode_dict = mode_dict or {}
        self.logger = logger
        self.cache: dict[str, float] = {}

    async def get_factor(self, kind: str, index_reader: Callable[[str], Awaitable[int]]) -> float:
        # kind: "current" | "voltage" | "energy_auto" | "kwh"
        if kind in self.cache:
            return self.cache[kind]

        match kind:
            case "current":
                idx = await index_reader("SCALE_CurrentIndex")
                val = self._lookup_factor(table_name=ScaleTable.CURRENT, idx=idx, default=0.01)

            case "voltage":
                idx = await index_reader("SCALE_VoltageIndex")
                val = self._lookup_factor(table_name=ScaleTable.VOLTAGE, idx=idx, default=1.0)

            case "energy_auto":
                idx = await index_reader("SCALE_EnergyIndex")
                base = self._lookup_factor(table_name=ScaleTable.ENERGY, idx=idx, default=1.0)
                post = float(self.table_dict.get("energy_post_multiplier", 0.001))
                val = base * post

            case "kwh" if (self.mode_dict.get("kwh", {}).get("mode") or "auto").lower() == "fixed":
                kwh_cfg = self.mode_dict.get("kwh", {})
                val = float(kwh_cfg.get("fixed_scale", 0.01))

            case "kwh":
                val = await self.get_factor("energy_auto", index_reader)

            case _:
                self.logger.warning(f"Unknown scale kind: {kind}")
                val = 1.0

        val = float(val)
        self.cache[kind] = val
        return val

    def invalidate(self, keys: list[str] | None = None):
        if keys:
            for k in keys:
                self.cache.pop(k, None)
        else:
            self.cache.clear()

    def _lookup_factor(self, table_name: ScaleTable, idx: int, default: float) -> float:
        table = self.table_dict.get(table_name, [])
        try:
            if 0 <= idx < len(table):
                return float(table[idx])
        except Exception:
            pass
        return float(default)
