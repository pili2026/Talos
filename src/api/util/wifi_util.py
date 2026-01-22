import logging
import string
from pathlib import Path
from typing import Iterable

from fastapi import HTTPException, status

from api.model.enum.wifi import SecurityType
from api.model.wifi import WiFiConnectRequest, WiFiNetwork, WpaNetworkRow

logger = logging.getLogger("WiFiUtil")


class WiFiUtil:
    @staticmethod
    def validate_connect_request(req: WiFiConnectRequest) -> None:
        """
        Validate connection request parameters.

        Raises:
            HTTPException: If parameters are invalid
        """
        # OPEN networks should not include password
        if req.security == SecurityType.OPEN and req.psk:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OPEN network must not include psk")

        # Encrypted networks must provide password
        if req.security != SecurityType.OPEN and not req.psk:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"{req.security.value} network requires psk"
            )

    @staticmethod
    def read_text(path: Path) -> str:
        """
        Safely read text file

        Args:
            path: File path

        Returns:
            File content (stripped); empty string if read fails
        """
        try:
            return path.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            return ""

    @staticmethod
    def mask_sensitive_args(cmd: list[str]) -> list[str]:
        """
        Mask sensitive parameters in command (e.g., passwords)

        Args:
            cmd: Original command list

        Returns:
            Command list with sensitive info masked
        """
        safe_cmd: list[str] = cmd.copy()
        # If there's a psk parameter, mask its value
        for i, arg in enumerate(safe_cmd):
            if i > 0 and safe_cmd[i - 1] == "psk":
                safe_cmd[i] = '"***"'
        return safe_cmd

    @staticmethod
    def parse_scan_results(
        text: str, *, current_ssid: str | None, current_bssid: str | None, group_by_ssid: bool = True
    ) -> list[WiFiNetwork]:
        """
        Parse wpa_cli scan_results output

        Args:
            text: scan_results raw output
            current_ssid: Currently connected SSID
            current_bssid: Currently connected BSSID
            group_by_ssid: Whether to group by SSID (keep only strongest AP per SSID)

        Returns:
            WiFi network list
        """
        lines: list[str] = (text or "").splitlines()
        if len(lines) <= 1:
            return []

        rows: list[str] = lines[1:]  # Skip header line
        all_item_list: list[WiFiNetwork] = []

        for raw_line in rows:
            raw_line = raw_line.strip()
            if not raw_line:
                continue

            # Try tab separator, fall back to space separator
            parts = raw_line.split("\t")
            if len(parts) < 4:
                parts = raw_line.split()

            if len(parts) < 4:
                continue

            bssid: str = parts[0].strip()
            freq: int | None = WiFiUtil.to_int(parts[1].strip()) if len(parts) >= 2 else None
            signal_dbm: int | None = WiFiUtil.to_int(parts[2].strip()) if len(parts) >= 3 else None
            if signal_dbm is None:
                signal_dbm = -100

            flags: str = parts[3].strip() if len(parts) >= 4 else ""
            raw_ssid: str = "\t".join(parts[4:]).strip() if len(parts) >= 5 else ""

            # Sanitize and validate SSID
            display_ssid, is_valid, invalid_reason = WiFiUtil._sanitize_ssid(raw_ssid)

            # Determine security type
            security = SecurityType.from_wpa_flags(flags)

            # Calculate signal strength percentage
            signal_strength: int = WiFiUtil._dbm_to_percent(int(signal_dbm))

            # Determine if currently in use
            in_use = False
            if current_bssid and bssid and bssid.lower() == current_bssid.lower():
                in_use = True
            elif current_ssid and raw_ssid and raw_ssid == current_ssid:
                in_use = True

            all_item_list.append(
                WiFiNetwork(
                    ssid=display_ssid,
                    raw_ssid=raw_ssid or None,
                    signal_strength=signal_strength,
                    security=security,
                    in_use=in_use,
                    bssid=bssid or None,
                    freq=freq,
                    is_valid=is_valid,
                    invalid_reason=invalid_reason,
                )
            )

        # Stable sort: in_use first, then signal strength
        all_item_list.sort(key=lambda x: (not x.in_use, -x.signal_strength))

        if not group_by_ssid:
            return all_item_list

        # group_by_ssid = True: keep best AP per display SSID
        best_by_ssid: dict[str, WiFiNetwork] = {}
        for item in all_item_list:
            key = item.ssid  # Use display SSID as key
            existing = best_by_ssid.get(key)
            if existing is None:
                best_by_ssid[key] = item
                continue

            # Replace if new item is in_use, or has stronger signal
            if (not existing.in_use and item.in_use) or (
                item.in_use == existing.in_use and item.signal_strength > existing.signal_strength
            ):
                best_by_ssid[key] = item

        grouped = list(best_by_ssid.values())
        grouped.sort(key=lambda x: (not x.in_use, -x.signal_strength))
        return grouped

    @staticmethod
    def to_int(v: str | None) -> int | None:
        """
        Safely convert string to integer

        Args:
            v: String value

        Returns:
            Integer value; None if conversion fails
        """
        if v is None:
            return None
        try:
            return int(v)
        except Exception:
            return None

    @staticmethod
    def pick_site_priority_decrement(used: set[int]) -> int:
        """
        Select unused priority in DECREMENT mode

        Starting from 4, decrement to select first unused value.

        Args:
            used: Set of used priorities

        Returns:
            Selected priority value
        """
        for priority in [4, 3, 2, 1, 0]:
            if priority not in used:
                return priority
        return 0

    @staticmethod
    def has_any_ssid(networks: list[WpaNetworkRow], ssids: Iterable[str]) -> bool:
        """
        Check if network list contains any of the specified SSIDs

        Args:
            networks: Network list
            ssids: SSIDs to check

        Returns:
            True if at least one SSID exists
        """
        ssid_set = set(ssids)
        return any(n.ssid in ssid_set for n in networks)

    @staticmethod
    def discover_wireless_interfaces() -> set[str]:
        """
        Discover wireless network interfaces on the system.

        This is a public helper function intended for use during dependency injection
        to identify available wireless interfaces.

        Returns:
            A set of wireless interface names.
        """
        base = Path("/sys/class/net")
        if not base.exists():
            return set()

        wireless_ifnames: set[str] = set()
        for p in base.iterdir():
            if p.name != "lo" and (p / "wireless").exists():
                wireless_ifnames.add(p.name)

        return wireless_ifnames

    @staticmethod
    def _sanitize_ssid(raw: str) -> tuple[str, bool, str | None]:
        """
        Sanitize and validate SSID

        Args:
            raw: Raw SSID

        Returns:
            (display_ssid, is_valid, invalid_reason)
        """
        if raw is None:
            return "(Hidden SSID)", True, None

        raw_str = raw.strip()
        if not raw_str:
            return "(Hidden SSID)", True, None

        # Check for null-byte pattern
        if "\\x00" in raw_str.lower():
            return "(Invalid SSID)", False, "Contains null-byte pattern (\\x00)"

        # Check length
        if len(raw_str) > 32:
            return "(Invalid SSID)", False, "SSID length > 32"

        # Check for non-printable characters
        non_printable = [ch for ch in raw_str if (not ch.isprintable()) or (ch in "\r\n\t")]
        if non_printable:
            return "(Invalid SSID)", False, "Contains non-printable/control characters"

        # SSID with only punctuation is valid but unusual
        if all(ch in string.punctuation for ch in raw_str):
            return raw_str, True, "SSID contains only punctuation (unusual but valid)"

        return raw_str, True, None

    @staticmethod
    def _dbm_to_percent(dbm: int) -> int:
        """
        Convert dBm signal strength to percentage

        Conversion formula:
        - >= -30 dBm: 100%
        - <= -90 dBm: 0%
        - Other: Linear mapping

        Args:
            dbm: dBm value

        Returns:
            Signal strength percentage (0-100)
        """
        if dbm >= -30:
            return 100
        if dbm <= -90:
            return 0
        return int((dbm + 90) * (100 / 60))
