from enum import StrEnum


class Radix(StrEnum):
    """Radix options for DeviceIdPolicy.

    - dec: legacy decimal-based code generation
    - hex: legacy hex-based code generation
    - device36: 3-char device code (series, slave, idx) for legacy cloud
    """

    DEC = "dec"
    HEX = "hex"
    DEVICE36 = "device36"
