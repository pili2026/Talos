import logging

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from model.enum.equipment_enum import EquipmentType
from model.enum.policy_enum import Radix

logger = logging.getLogger("DeviceIdPolicy")


class DeviceIdPolicy(BaseModel):
    """Global DeviceID policy + utility methods"""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, populate_by_name=True)

    series: int = Field(0, ge=0, le=15, alias="SERIES")
    width: int = Field(3, ge=1, le=8, alias="WIDTH")
    radix: Radix = Field(Radix.HEX, alias="RADIX")
    uppercase: bool = Field(True, alias="UPPERCASE")
    prefix: str = Field("", alias="PREFIX")

    # -------------------------
    # Utility methods
    # -------------------------
    def parse_slave_id(self, slave_id: str) -> int:
        """Convert slave_id (0-9, a-z) to int; fallback=0 if invalid"""
        try:
            return int(str(slave_id).strip().lower(), 36)
        except Exception:
            logger.warning(f"Invalid slave_id={slave_id!r}, fallback=0")
            return 0

    def generate_code(self, slave_id: str, idx: int) -> str:
        """Generate code string according to the policy"""
        if not 0 <= idx <= 15:
            logger.warning(f"idx out of range (0..15): {idx}, fallback=0")
            idx = 0

        parsed_slave_id: int = self.parse_slave_id(slave_id)

        if self.radix == Radix.HEX:
            base = self.series << ((self.width - 1) * 4)
            code = base + parsed_slave_id * 16 + idx
            fmt = "X" if self.uppercase else "x"
            return f"{code:0{self.width}{fmt}}"

        base = self.series * (10 ** (self.width - 1))
        code = base + parsed_slave_id * 16 + idx
        return f"{code:0{self.width}d}"

    def build_device_id(self, gateway_id: str, slave_id: str, idx: int, eq_suffix: EquipmentType = "") -> str:
        """Final public Function"""
        code = self.generate_code(slave_id, idx)
        return f"{gateway_id}_{self.prefix}{code}{eq_suffix}"


# ---- Global singleton ----
POLICY = DeviceIdPolicy()


def load_device_id_policy(system_config: dict | None) -> None:
    """Call once at startup to load settings; keep defaults on error"""
    global POLICY
    section = (system_config or {}).get("DEVICE_ID_POLICY") or (system_config or {}).get("device_id_policy") or {}
    try:
        POLICY = DeviceIdPolicy.model_validate(section)
    except ValidationError as e:
        logger.warning(f"Invalid config; using defaults. detail={e}")
