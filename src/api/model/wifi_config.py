import os
from pydantic import BaseModel, ConfigDict, Field, field_validator
from api.model.enum.wifi import SitePriorityMode


class WiFiConfig(BaseModel):
    """
    WiFi Service Configuration (loaded from environment variables).

    Environment Variables:
    - TALOS_WIFI_DEFAULT_IFNAME: Default network interface name (default: wlan0)
    - TALOS_WIFI_USE_SUDO: Whether to run wpa_cli with sudo (default: true)
    - TALOS_WIFI_TIMEOUT_SEC: wpa_cli command timeout in seconds (default: 3.0)
    - TALOS_WIFI_SCAN_WAIT_SEC: Seconds to wait for scan results (default: 2.0)
    - TALOS_WIFI_RESCUE_SSIDS: Rescue SSID list, comma-separated (default: imaoffice1)
    - TALOS_WIFI_SITE_PRIORITY_MODE: Site priority mode (default: decrement)
    """

    model_config = ConfigDict(frozen=True)

    default_ifname: str = Field(default="wlan0", description="Default network interface")
    use_sudo: bool = Field(default=True, description="Use sudo for wpa_cli commands")
    timeout_sec: float = Field(default=3.0, gt=0, description="Command timeout in seconds")
    scan_wait_sec: float = Field(default=2.0, gt=0, description="Scan wait time in seconds")
    rescue_ssids: set[str] = Field(default_factory=lambda: {"imaoffice1"}, description="Rescue SSID set")
    site_priority_mode: SitePriorityMode = Field(
        default=SitePriorityMode.DECREMENT, description="Site network priority assignment mode"
    )

    @field_validator("rescue_ssids")
    @classmethod
    def validate_rescue_ssids(cls, v: set[str]) -> set[str]:
        """Ensure rescue_ssids is not empty."""
        if not v:
            raise ValueError("rescue_ssids cannot be empty")
        return v

    @field_validator("timeout_sec", "scan_wait_sec")
    @classmethod
    def validate_positive(cls, v: float) -> float:
        """Ensure timeout values are positive."""
        if v <= 0:
            raise ValueError("Timeout must be positive")
        return v

    @classmethod
    def from_env(cls) -> "WiFiConfig":
        """
        Build a config instance from environment variables.

        Returns:
            WiFiConfig instance with values loaded from environment

        Example:
            >>> os.environ["TALOS_WIFI_DEFAULT_IFNAME"] = "wlan1"
            >>> config = WiFiConfig.from_env()
            >>> config.default_ifname
            'wlan1'
        """
        # Parse rescue SSID list
        rescue_str = os.getenv("TALOS_WIFI_RESCUE_SSIDS", "imaoffice1").strip()
        rescue_ssids = {s.strip() for s in rescue_str.split(",") if s.strip()}

        # Parse site priority mode
        mode_str = os.getenv("TALOS_WIFI_SITE_PRIORITY_MODE", "decrement").strip().lower()
        try:
            mode = SitePriorityMode(mode_str)
        except ValueError:
            mode = SitePriorityMode.DECREMENT

        # Parse sudo setting
        use_sudo_str = os.getenv("TALOS_WIFI_USE_SUDO", "true").strip().lower()
        use_sudo = use_sudo_str in ("true", "1", "yes")

        return cls(
            default_ifname=os.getenv("TALOS_WIFI_DEFAULT_IFNAME", "wlan0").strip(),
            use_sudo=use_sudo,
            timeout_sec=float(os.getenv("TALOS_WIFI_TIMEOUT_SEC", "3.0")),
            scan_wait_sec=float(os.getenv("TALOS_WIFI_SCAN_WAIT_SEC", "2.0")),
            rescue_ssids=rescue_ssids,
            site_priority_mode=mode,
        )
