from typing import Any, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from core.model.device_constant import REG_RW_ON_OFF


class OnOffBinding(BaseModel):
    """
    Translate abstract TURN_ON / TURN_OFF into multiple DO pin writes.
    - targets: DO register names to be controlled together (must exist in register_map, e.g., "DOut01")
    - on/off: Values to be written after translation (for active-low, swap on/off)
    """

    model_config = ConfigDict(frozen=True, extra="ignore")  # immutable, ignore extra fields
    targets: list[str] = Field(min_length=1)
    on: int = 1
    off: int = 0
    write_mode: str = "bit"  # reserved

    @field_validator("targets", mode="before")
    @classmethod
    def _normalize_targets(cls, v):
        if v is None:
            return []
        if isinstance(v, (set, tuple)):
            v = list(v)
        return [str(x) for x in v]

    @field_validator("on", "off", mode="before")
    @classmethod
    def _coerce_int(cls, v):
        return int(v) if v is not None else v


class CapabilityResolver:
    """
    Merge precedence for capability lookup:
      1) instance_overrides[model][slave_id].capabilities
      2) driver_configs[model].capabilities
      3) Fallback heuristics:
         - Driver register_map contains RW_ON_OFF and is writable
         - Driver type/device_type belongs to {"inverter", "vfd", "inverter_vfd"}
    """

    def __init__(self, driver_config: dict[str, dict], instance_config: dict[str, Any] | None = None):
        self._driver_config = driver_config or {}
        self._instance_config = instance_config or {}

    # ---- public API ----
    def supports_on_off(self, model: str, slave_id: Union[str, int]) -> bool:
        # (1) Explicit declaration from instance overrides
        ov_caps = self._instance_config.get(model, {}).get(str(slave_id), {}).get("capabilities", {}) or {}
        if "supports_on_off" in ov_caps:
            return bool(ov_caps["supports_on_off"])

        # (2) Explicit declaration from driver caps
        drv_caps = self._driver_caps(model)
        if "supports_on_off" in drv_caps:
            return bool(drv_caps["supports_on_off"])

        # (3a) RW_ON_OFF exists and writable → treat as supporting on/off
        reg_map = self._driver_register_map(model)
        rw = reg_map.get(REG_RW_ON_OFF)
        if isinstance(rw, dict) and rw.get("writable"):
            return True

        # (3b) Type hint (inverter/vfd family) → treat as supporting on/off
        dtype = self._driver_type(model)
        if isinstance(dtype, str) and dtype.lower() in {"inverter", "vfd", "inverter_vfd"}:
            return True

        return False

    def get_on_off_binding(self, model: str, slave_id: Union[str, int]) -> OnOffBinding | None:
        # First check instance overrides
        ov_caps = self._instance_config.get(model, {}).get(str(slave_id), {}).get("capabilities", {}) or {}
        raw = ov_caps.get("on_off_binding")
        if raw is None:
            # Then fallback to driver defaults
            raw = self._driver_caps(model).get("on_off_binding")

        if not raw:
            return None

        try:
            return OnOffBinding.model_validate(raw)
        except ValidationError:
            return None

    # ---- helpers ----
    def _driver_caps(self, model: str) -> dict:
        return self._driver_config.get(model, {}).get("capabilities", {}) or {}

    def _driver_register_map(self, model: str) -> dict:
        return self._driver_config.get(model, {}).get("register_map", {}) or {}

    def _driver_type(self, model: str) -> str | None:
        drv = self._driver_config.get(model, {}) or {}
        return drv.get("type") or drv.get("device_type") or drv.get("model_type")
