from pydantic import BaseModel, ConfigDict, Field

from api.model.enum.wifi import SecurityType
from api.model.responses import BaseResponse


class WpaNetworkRow(BaseModel):
    """
    wpa_supplicant network configuration row.

    Internal model representing a network entry from 'wpa_cli list_networks'.
    """

    model_config = ConfigDict(frozen=True)

    network_id: int = Field(..., description="Network ID in wpa_supplicant")
    ssid: str = Field(..., description="Network SSID")
    bssid: str | None = Field(None, description="AP BSSID (if locked)")
    flags: str | None = Field(None, description="Network flags (e.g., [CURRENT])")


class WpaStatus(BaseModel):
    """
    Internal model for wpa_cli status output.

    This is a lightweight internal representation of wpa_supplicant status,
    distinct from WiFiStatusInfo which is the public API response model.
    """

    model_config = ConfigDict(frozen=True)

    ssid: str | None = Field(None, description="Connected SSID")
    bssid: str | None = Field(None, description="AP BSSID")
    freq: int | None = Field(None, description="Frequency in MHz")
    wpa_state: str | None = Field(None, description="WPA state (e.g., COMPLETED)")
    ip_address: str | None = Field(None, description="Assigned IP address")
    network_id: int | None = Field(None, description="Network ID")
    key_mgmt: str | None = Field(None, description="Key management (e.g., WPA2-PSK)")

    @staticmethod
    def parse_key_value(text: str) -> dict[str, str]:
        """
        Parse key=value format text

        Args:
            text: Raw text

        Returns:
            Key-value dictionary
        """
        data: dict[str, str] = {}
        for line in (text or "").splitlines():
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
        return data

    # TODO: Need to Move to Utility Module
    @staticmethod
    def _to_int(v: str | None) -> int | None:
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

    @classmethod
    def from_wpa_output(cls, text: str) -> "WpaStatus":
        """
        Parse wpa_cli status output into a WpaStatus object.

        Args:
            text: Raw output from 'wpa_cli status'

        Returns:
            WpaStatus instance

        Example:
            >>> text = "ssid=MyNetwork\\nbssid=00:11:22:33:44:55\\n..."
            >>> status = WpaStatus.from_wpa_output(text)
            >>> status.ssid
            'MyNetwork'
        """

        data: dict[str, str] = WpaStatus.parse_key_value(text)

        return cls(
            ssid=data.get("ssid"),
            bssid=data.get("bssid"),
            freq=WpaStatus._to_int(data.get("freq")),
            wpa_state=data.get("wpa_state"),
            ip_address=data.get("ip_address"),
            network_id=WpaStatus._to_int(data.get("id")),
            key_mgmt=data.get("key_mgmt"),
        )

    @property
    def is_connected(self) -> bool:
        """
        Check if WiFi is connected.

        Connected means:
        - wpa_state is COMPLETED
        - SSID is present
        - IP address is assigned

        Returns:
            True if connected, False otherwise
        """
        return self.wpa_state == "COMPLETED" and bool(self.ssid) and bool(self.ip_address)


class WiFiConnectRequest(BaseModel):
    ssid: str = Field(..., min_length=1, max_length=32)
    security: SecurityType = Field(..., description="Security type inferred from scan")
    psk: str | None = Field(None, max_length=63, description="WPA/WPA2/WPA3-PSK password")
    bssid: str | None = Field(None, description="Optional AP BSSID to lock onto (advanced)")
    priority: int | None = Field(None, ge=0, le=100)
    save_config: bool = True


class WiFiConnectResponse(BaseResponse):
    interface: str | None = None
    ssid: str
    accepted: bool
    applied_network_id: int | None = None
    applied_priority: int | None = None
    applied_bssid: str | None = None
    bssid_locked: bool = False
    saved: bool = False
    save_error: str | None = None
    note: str | None = None

    rescue_present: bool = True
    warnings: list[str] = []

    recommended_poll_interval_ms: int = 1000
    recommended_timeout_ms: int = 30000


class WiFiStatusInfo(BaseModel):
    """
    Current Wi-Fi connection status info (wpa_cli status).
    """

    interface: str = Field(..., description="Wi-Fi interface name (e.g., wlan0)")
    ssid: str | None = Field(None, description="Connected SSID")
    bssid: str | None = Field(None, description="AP BSSID")
    freq: int | None = Field(None, description="Frequency MHz")
    wpa_state: str | None = Field(None, description="wpa_state (e.g., COMPLETED)")
    ip_address: str | None = Field(None, description="Assigned IP address")
    network_id: int | None = Field(None, description="wpa_cli network id")
    key_mgmt: str | None = Field(None, description="Key management (e.g., WPA2-PSK)")
    is_connected: bool = Field(..., description="Whether Wi-Fi is connected")


class WiFiStatusResponse(BaseResponse):
    """
    Response model for Wi-Fi status.
    """

    status_info: WiFiStatusInfo


class WiFiNetwork(BaseModel):
    ssid: str
    raw_ssid: str | None = None
    signal_strength: int = Field(..., ge=0, le=100)
    security: SecurityType
    in_use: bool = False
    bssid: str | None = None
    freq: int | None = None
    is_valid: bool
    invalid_reason: str | None = None


class WiFiListResponse(BaseResponse):
    interface: str | None = None
    networks: list[WiFiNetwork]
    total_count: int
    current_ssid: str | None = None


class WiFiInterfaceInfo(BaseModel):
    ifname: str = Field(..., description="Interface name (e.g., wlan0)")
    is_wireless: bool = Field(..., description="Whether interface is wireless (has /sys/class/net/<ifname>/wireless)")
    is_up: bool | None = Field(None, description="Whether interface operstate is up")
    mac: str | None = Field(None, description="MAC address")
    driver: str | None = Field(None, description="Kernel driver name (best-effort)")
    phy: str | None = Field(None, description="wiphy name (best-effort)")
    is_default: bool = Field(False, description="Whether this is service default_ifname")


class WiFiInterfacesResponse(BaseResponse):
    interfaces: list[WiFiInterfaceInfo] = Field(default_factory=list)
    total_count: int = 0

    recommended_ifname: str | None = Field(
        default=None,
        description="Recommended interface for FE (usually service default_ifname)",
    )
