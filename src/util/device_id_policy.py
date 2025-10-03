import logging
from schema.system_config_schema import SystemConfig, DeviceIdPolicyConfig
from model.enum.equipment_enum import EquipmentType
from model.enum.policy_enum import Radix

logger = logging.getLogger("DeviceIdPolicy")


class DeviceIdPolicy:
    """
    Device ID Generator (Business Logic)

    Responsibility: Use DeviceIdPolicyConfig to generate Device IDs
    Does not redefine fields, only holds a config reference
    """

    def __init__(self, config: DeviceIdPolicyConfig):
        """
        Initialize

        Args:
            config: Device ID policy configuration
        """
        self._config = config

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

        parsed_slave_id = self.parse_slave_id(slave_id)
        radix = Radix(self._config.RADIX.lower())

        if radix == Radix.HEX:
            base = self._config.SERIES << ((self._config.WIDTH - 1) * 4)
            code = base + parsed_slave_id * 16 + idx
            fmt = "X" if self._config.UPPERCASE else "x"
            return f"{code:0{self._config.WIDTH}{fmt}}"

        base = self._config.SERIES * (10 ** (self._config.WIDTH - 1))
        code = base + parsed_slave_id * 16 + idx
        return f"{code:0{self._config.WIDTH}d}"

    def build_device_id(self, gateway_id: str, slave_id: str, idx: int, eq_suffix: EquipmentType = "") -> str:
        """Build complete device ID"""
        code = self.generate_code(slave_id, idx)
        return f"{gateway_id}_{self._config.PREFIX}{code}{eq_suffix}"

    def __repr__(self) -> str:
        return (
            f"DeviceIdPolicy(series={self._config.SERIES}, " f"width={self._config.WIDTH}, radix={self._config.RADIX})"
        )


# ---- Global singleton ----
POLICY: DeviceIdPolicy | None = None


def load_device_id_policy(system_config: SystemConfig) -> None:
    """
    Load Device ID Policy (global singleton)

    Args:
        system_config: System configuration
    """
    global POLICY
    try:
        POLICY = DeviceIdPolicy(system_config.DEVICE_ID_POLICY)
        logger.info(f"Loaded {POLICY}")
    except Exception as e:
        logger.error(f"Failed to load DeviceIdPolicy: {e}", exc_info=True)
        POLICY = DeviceIdPolicy(DeviceIdPolicyConfig())
        logger.warning("Using default DeviceIdPolicy")


def get_policy() -> DeviceIdPolicy:
    """
    Get the current policy

    Returns:
        DeviceIdPolicy: The current policy instance

    Raises:
        RuntimeError: If the policy has not been loaded yet
    """
    if POLICY is None:
        logger.error(
            "DeviceIdPolicy not initialized! "
            "load_device_id_policy() must be called during startup. "
            "Creating default policy as fallback."
        )
        return DeviceIdPolicy(DeviceIdPolicyConfig())
    return POLICY
