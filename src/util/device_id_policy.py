# util/device_id_policy.py
import logging

from model.enum.equipment_enum import EquipmentType
from model.enum.policy_enum import Radix
from schema.system_config_schema import DeviceIdPolicyConfig, SystemConfig

logger = logging.getLogger("DeviceIdPolicy")


class DeviceIdPolicy:
    """
    Device ID Generator (Business Logic).

    Responsibility: Use DeviceIdPolicyConfig to generate Device IDs.
    Does not redefine fields, only holds a config reference.
    """

    def __init__(self, config: DeviceIdPolicyConfig):
        """
        Initialize.

        Args:
            config: Device ID policy configuration
        """
        self._config = config

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def parse_slave_id(self, slave_id: str | int) -> int:
        """Parse slave_id into integer with safe fallback."""
        if isinstance(slave_id, int):
            return slave_id

        s = str(slave_id).strip().lower()
        try:
            return int(s, 10)  # Default decimal
        except Exception:
            logger.warning("Invalid slave_id=%r, fallback=0", slave_id)
            return 0

    # ------------------------------------------------------------------
    # Core code generation
    # ------------------------------------------------------------------
    def generate_code(self, slave_id: int, idx: int) -> str:
        """
        Generate the short device code (without gateway / suffix).

        Supported radix modes:
        - dec: decimal-based legacy code (width digits)
        - hex: hex-based legacy code (width hex digits)
        - device36: 3-char code: [series][slave][idx]
                    series: 0-15 (0-9A-F)
                    slave:  0-35 (0-9A-Z)
                    idx:    0-15 (0-9A-F)
        """
        parsed_slave_id = int(slave_id)
        radix = Radix(self._config.RADIX.lower())

        # ===== New: DEVICE36 mode for legacy cloud =====
        if radix == Radix.DEVICE36:
            # series must be 0..15 (single hex digit)
            series = self._config.SERIES
            if not 0 <= series <= 15:
                logger.warning(
                    "SERIES out of range 0..15 for DEVICE36, fallback=0 (SERIES=%r)",
                    series,
                )
                series = 0

            # slave_id encoded as base-36 single digit: 0-9A-Z (0..35)
            if parsed_slave_id < 0 or parsed_slave_id > 35:
                logger.warning(
                    "slave_id out of range 0..35 for DEVICE36: %r, clamped",
                    parsed_slave_id,
                )
                parsed_slave_id = max(0, min(parsed_slave_id, 35))

            # idx is still 0..15 (single hex nibble)
            if not 0 <= idx <= 15:
                logger.warning(
                    "idx out of range 0..15 for DEVICE36: %r, fallback=0",
                    idx,
                )
                idx = 0

            # Alphabet for base-36 (upper or lower depending on config)
            alphabet = (
                "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                if self._config.UPPERCASE
                else "0123456789abcdefghijklmnopqrstuvwxyz"
            )

            series_ch = alphabet[series]  # 1st char: series (0..F)
            slave_ch = alphabet[parsed_slave_id]  # 2nd char: slave (0..Z)
            idx_ch = alphabet[idx]  # 3rd char: idx (0..F)

            return f"{series_ch}{slave_ch}{idx_ch}"

        # ===== Legacy HEX mode (unchanged) =====
        if radix == Radix.HEX:
            # TODO: Need to support more than 16 devices per slave?
            if not 0 <= idx <= 15:
                logger.warning("idx out of range (0..15): %r, fallback=0", idx)
                idx = 0

            # In HEX/DEC modes we still treat slave_id as integer directly.
            base = self._config.SERIES << ((self._config.WIDTH - 1) * 4)
            code = base + parsed_slave_id * 16 + idx
            fmt = "X" if self._config.UPPERCASE else "x"
            return f"{code:0{self._config.WIDTH}{fmt}}"

        # ===== Legacy DEC mode (unchanged) =====
        # TODO: Need to support more than 16 devices per slave?
        if not 0 <= idx <= 15:
            logger.warning("idx out of range (0..15): %r, fallback=0", idx)
            idx = 0

        base = self._config.SERIES * (10 ** (self._config.WIDTH - 1))
        code = base + parsed_slave_id * 16 + idx
        return f"{code:0{self._config.WIDTH}d}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def build_device_id(
        self,
        gateway_id: str,
        slave_id: int | str,
        idx: int,
        eq_suffix: EquipmentType | str = "",
    ) -> str:
        """
        Build full DeviceID: <GatewayID>_<CODE><SUFFIX>.

        Examples (DEVICE36 mode):
            gateway_id="05346051113", SERIES=0, slave_id=16, idx=0, suffix="SE"
            → "05346051113_0G0SE"
        """
        parsed_slave = self.parse_slave_id(slave_id)
        code = self.generate_code(parsed_slave, idx)
        return f"{gateway_id}_{self._config.PREFIX}{code}{eq_suffix}"

    def __repr__(self) -> str:
        return "DeviceIdPolicy(series=%r, width=%r, radix=%r)" % (
            self._config.SERIES,
            self._config.WIDTH,
            self._config.RADIX,
        )


# ---- Global singleton ----
POLICY: DeviceIdPolicy | None = None


def load_device_id_policy(system_config: SystemConfig) -> None:
    """
    Load Device ID Policy (global singleton).

    Args:
        system_config: System configuration
    """
    global POLICY
    try:
        POLICY = DeviceIdPolicy(system_config.DEVICE_ID_POLICY)
        logger.info("Loaded %s", POLICY)
    except Exception:
        logger.exception("Failed to load DeviceIdPolicy, using default config")
        POLICY = DeviceIdPolicy(DeviceIdPolicyConfig())
        logger.warning("Using default DeviceIdPolicy")


def get_policy() -> DeviceIdPolicy:
    """
    Get the current policy instance.

    If the policy was not initialized, creates a default policy and logs an error.
    """
    if POLICY is None:
        logger.error(
            "DeviceIdPolicy not initialized! "
            "load_device_id_policy() must be called during startup. "
            "Creating default policy as fallback."
        )
        return DeviceIdPolicy(DeviceIdPolicyConfig())
    return POLICY
