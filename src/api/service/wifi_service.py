"""
WiFi Service Layer

Handles business logic related to WiFi management:
- Scanning for available networks
- Connecting to WiFi networks
- Getting current connection status
"""

import logging
import subprocess
import re
from typing import Any

from api.model.responses import WiFiNetwork, WiFiListResponse, WiFiConnectionResponse
from api.model.enums import ResponseStatus

logger = logging.getLogger(__name__)


class WiFiService:
    """
    WiFi Operation Service

    Responsibilities:
    - Scan and list available WiFi networks
    - Connect to specified WiFi network
    - Get current WiFi status
    - Manage NetworkManager operations (Linux)
    """

    def __init__(self):
        self._check_network_manager()

    def _check_network_manager(self) -> bool:
        """
        Check if NetworkManager is available on the system.

        Returns:
            bool: True if NetworkManager is available.
        """
        try:
            result = subprocess.run(
                ["which", "nmcli"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                logger.info("NetworkManager (nmcli) is available")
                return True
            else:
                logger.warning("NetworkManager (nmcli) not found on system")
                return False
        except Exception as e:
            logger.error(f"Error checking for NetworkManager: {e}")
            return False

    async def scan_networks(self) -> WiFiListResponse:
        """
        Scan for available WiFi networks.

        Returns:
            WiFiListResponse: List of available networks.
        """
        try:
            # Rescan for fresh results
            subprocess.run(
                ["nmcli", "device", "wifi", "rescan"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            # Get WiFi list
            result = subprocess.run(
                ["nmcli", "-f", "SSID,SIGNAL,SECURITY,IN-USE,BSSID", "device", "wifi", "list"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                logger.error(f"Failed to scan WiFi networks: {result.stderr}")
                return WiFiListResponse(
                    status=ResponseStatus.ERROR,
                    networks=[],
                    total_count=0,
                    message="Failed to scan WiFi networks",
                )

            networks = self._parse_wifi_list(result.stdout)
            current_ssid = self._get_current_ssid()

            return WiFiListResponse(
                status=ResponseStatus.SUCCESS,
                networks=networks,
                total_count=len(networks),
                current_ssid=current_ssid,
            )

        except subprocess.TimeoutExpired:
            logger.error("WiFi scan timed out")
            return WiFiListResponse(
                status=ResponseStatus.ERROR,
                networks=[],
                total_count=0,
                message="WiFi scan timed out",
            )
        except Exception as e:
            logger.error(f"Error scanning WiFi networks: {e}", exc_info=True)
            return WiFiListResponse(
                status=ResponseStatus.ERROR,
                networks=[],
                total_count=0,
                message=f"Error scanning networks: {str(e)}",
            )

    async def connect_to_network(self, ssid: str, password: str | None = None) -> WiFiConnectionResponse:
        """
        Connect to a WiFi network.

        Args:
            ssid: Network SSID to connect to.
            password: Network password (optional for open networks).

        Returns:
            WiFiConnectionResponse: Connection result.
        """
        try:
            # Check if we already have a connection profile for this network
            check_result = subprocess.run(
                ["nmcli", "-t", "-f", "NAME", "connection", "show"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            has_profile = ssid in check_result.stdout

            if has_profile:
                # Use existing connection
                result = subprocess.run(
                    ["nmcli", "connection", "up", ssid],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            else:
                # Create new connection
                if password:
                    result = subprocess.run(
                        ["nmcli", "device", "wifi", "connect", ssid, "password", password],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                else:
                    result = subprocess.run(
                        ["nmcli", "device", "wifi", "connect", ssid],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )

            if result.returncode == 0:
                ip_address = self._get_current_ip()
                return WiFiConnectionResponse(
                    status=ResponseStatus.SUCCESS,
                    ssid=ssid,
                    connected=True,
                    ip_address=ip_address,
                    message="Successfully connected to WiFi network",
                )
            else:
                logger.error(f"Failed to connect to {ssid}: {result.stderr}")
                return WiFiConnectionResponse(
                    status=ResponseStatus.ERROR,
                    ssid=ssid,
                    connected=False,
                    message=f"Failed to connect: {result.stderr}",
                )

        except subprocess.TimeoutExpired:
            logger.error(f"Connection to {ssid} timed out")
            return WiFiConnectionResponse(
                status=ResponseStatus.ERROR,
                ssid=ssid,
                connected=False,
                message="Connection attempt timed out",
            )
        except Exception as e:
            logger.error(f"Error connecting to WiFi: {e}", exc_info=True)
            return WiFiConnectionResponse(
                status=ResponseStatus.ERROR,
                ssid=ssid,
                connected=False,
                message=f"Connection error: {str(e)}",
            )

    async def disconnect_network(self) -> dict[str, Any]:
        """
        Disconnect from current WiFi network.

        Returns:
            dict: Disconnection result.
        """
        try:
            current_ssid = self._get_current_ssid()
            if not current_ssid:
                return {
                    "status": "success",
                    "message": "No active WiFi connection",
                }

            result = subprocess.run(
                ["nmcli", "connection", "down", current_ssid],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                return {
                    "status": "success",
                    "message": f"Disconnected from {current_ssid}",
                    "previous_ssid": current_ssid,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to disconnect: {result.stderr}",
                }

        except Exception as e:
            logger.error(f"Error disconnecting WiFi: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"Disconnection error: {str(e)}",
            }

    def _parse_wifi_list(self, output: str) -> list[WiFiNetwork]:
        """
        Parse nmcli WiFi list output.

        Args:
            output: Raw nmcli output.

        Returns:
            list[WiFiNetwork]: Parsed network list.
        """
        networks = []
        lines = output.strip().split("\n")

        # Skip header line
        for line in lines[1:]:
            parts = line.split()
            if len(parts) < 3:
                continue

            try:
                # Check if network is in use (marked with *)
                in_use = parts[0] == "*"
                start_idx = 1 if in_use else 0

                ssid = parts[start_idx]
                if not ssid or ssid == "--":
                    continue

                signal = int(parts[start_idx + 1]) if parts[start_idx + 1].isdigit() else 0
                security = parts[start_idx + 2] if len(parts) > start_idx + 2 else "Unknown"
                bssid = parts[start_idx + 3] if len(parts) > start_idx + 3 else None

                networks.append(
                    WiFiNetwork(
                        ssid=ssid,
                        signal_strength=signal,
                        security=security,
                        in_use=in_use,
                        bssid=bssid,
                    )
                )
            except (ValueError, IndexError) as e:
                logger.warning(f"Failed to parse WiFi line: {line}, error: {e}")
                continue

        return networks

    def _get_current_ssid(self) -> str | None:
        """
        Get the SSID of the currently connected network.

        Returns:
            str | None: Current SSID or None if not connected.
        """
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "active,ssid", "device", "wifi"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line.startswith("yes:"):
                        return line.split(":", 1)[1]
            return None
        except Exception as e:
            logger.error(f"Error getting current SSID: {e}")
            return None

    def _get_current_ip(self) -> str | None:
        """
        Get the current IP address of the WiFi interface only.

        Returns:
            str | None: IP address or None if not available.
        """
        try:
            # Get WiFi device name first
            wifi_device = self._get_wifi_device()
            if not wifi_device:
                return None

            result = subprocess.run(
                ["nmcli", "-g", "IP4.ADDRESS", "device", "show", wifi_device],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0:
                # Extract IP from format like "192.168.1.100/24"
                match = re.search(r"(\d+\.\d+\.\d+\.\d+)", result.stdout)
                if match:
                    return match.group(1)
            return None
        except Exception as e:
            logger.error(f"Error getting current WiFi IP: {e}")
            return None

    def _get_wifi_device(self) -> str | None:
        """
        Get the WiFi device name (e.g., wlan0, wlp2s0).

        Returns:
            str | None: WiFi device name or None if not found.
        """
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "DEVICE,TYPE", "device"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    parts = line.split(":")
                    if len(parts) == 2 and parts[1] == "wifi":
                        return parts[0]
            return None
        except Exception as e:
            logger.error(f"Error getting WiFi device: {e}")
            return None

    def _get_ethernet_status(self) -> dict[str, Any]:
        """
        Get ethernet connection status and IP address.

        Returns:
            dict: Ethernet status information.
        """
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            ethernet_connected = False
            ethernet_device = None
            ethernet_ip = None

            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    parts = line.split(":")
                    if len(parts) == 3 and parts[1] == "ethernet":
                        ethernet_device = parts[0]
                        ethernet_connected = parts[2] == "connected"
                        break

            # Get IP if ethernet is connected
            if ethernet_connected and ethernet_device:
                ip_result = subprocess.run(
                    ["nmcli", "-g", "IP4.ADDRESS", "device", "show", ethernet_device],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )

                if ip_result.returncode == 0:
                    match = re.search(r"(\d+\.\d+\.\d+\.\d+)", ip_result.stdout)
                    if match:
                        ethernet_ip = match.group(1)

            return {
                "connected": ethernet_connected,
                "device": ethernet_device,
                "ip_address": ethernet_ip,
            }

        except Exception as e:
            logger.error(f"Error getting ethernet status: {e}")
            return {
                "connected": False,
                "device": None,
                "ip_address": None,
            }
