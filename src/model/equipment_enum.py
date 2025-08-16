from enum import StrEnum


class EqType(StrEnum):
    """
    Enumeration for equipment types in POC Sender.

    Each member's value is the short string code used in the legacy XMS DeviceID.
    """

    GW = "GW"  # Gateway / IMA Box
    CI = "CI"  # Inverter (VFD)
    SR = "SR"  # Digital Input module
    SE = "SE"  # Power Meter
    SP = "SP"  # Pressure Gauge
    ST = "ST"  # Thermometer
    SF = "SF"  # Flowmeter
