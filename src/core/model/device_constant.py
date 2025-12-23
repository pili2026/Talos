REG_RW_ON_OFF = (
    "RW_ON_OFF"  # Already Added in device_constant_enums.py, kept here for completeness, can be removed later if needed
)
HI_SHIFT, MD_SHIFT = 32, 16
DEFAULT_MISSING_VALUE = -1

# Explicit semantic constants
INVERTER_STATUS_OFFLINE_CODE = 9
INVERTER_OFFLINE_PROBE_KEYS = ("KWH", "VOLTAGE", "CURRENT", "KW", "HZ")

INVALID_U16_SENTINEL = 0xFFFF  # 16-bit invalid value (65535)
INVALID_U32_SENTINEL = 0xFFFFFFFF  # 32-bit invalid value (future use)

# Power Meter Field Definitions
POWER_METER_FIELDS = {
    # Field name: {"common": bool, "round": int}
    "AverageVoltage": {"common": True, "round": 2},
    "AverageCurrent": {"common": True, "round": 2},
    "Phase_A_Current": {"common": True, "round": 2},
    "Phase_B_Current": {"common": True, "round": 2},
    "Phase_C_Current": {"common": True, "round": 2},
    "Kw": {"common": True, "round": 2},
    "Kva": {"common": True, "round": 2},
    "Kvar": {"common": True, "round": 2},
    "AveragePowerFactor": {"common": True, "round": 3},  # Special: 3 decimals
    "Kwh": {"common": False, "round": 2},  # Not common (pattern-dependent)
    "Kvarh": {"common": False, "round": 2},
}
