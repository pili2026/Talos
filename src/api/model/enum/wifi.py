from enum import StrEnum


class SecurityType(StrEnum):
    OPEN = "OPEN"
    WEP = "WEP"
    WPA = "WPA"
    WPA2 = "WPA2"
    WPA3 = "WPA3"
    WPA_WPA2 = "WPA/WPA2"
    WPA2_WPA3 = "WPA2/WPA3"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_wpa_flags(cls, flags: str) -> "SecurityType":
        """
        Parse wpa_cli scan_results flags into SecurityType.

        Examples:
        [WPA2-PSK-CCMP][ESS]
        [WPA-PSK-CCMP+TKIP][WPA2-PSK-CCMP+TKIP][ESS]
        [WPA3-SAE-CCMP][ESS]
        [ESS]
        """
        if not flags:
            return cls.UNKNOWN

        f = flags.upper()

        has_wpa = "WPA-PSK" in f
        has_wpa2 = "WPA2" in f
        has_wpa3 = "SAE" in f or "WPA3" in f
        has_wep = "WEP" in f
        has_ess = "ESS" in f

        # Mixed modes (order matters)
        if has_wpa2 and has_wpa3:
            return cls.WPA2_WPA3
        if has_wpa and has_wpa2:
            return cls.WPA_WPA2

        # Single modes
        if has_wpa3:
            return cls.WPA3
        if has_wpa2:
            return cls.WPA2
        if has_wpa:
            return cls.WPA
        if has_wep:
            return cls.WEP

        # Open network (ESS only)
        if has_ess:
            return cls.OPEN

        return cls.UNKNOWN


class SitePriorityMode(StrEnum):
    FIXED_4 = "fixed_4"
    DECREMENT = "decrement"
