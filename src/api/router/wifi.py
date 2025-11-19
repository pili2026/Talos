"""
WiFi Management Router

Defines all API endpoints related to WiFi network management.
"""

from fastapi import APIRouter, Depends

from api.dependency import get_wifi_service
from api.model.requests import WiFiConnectRequest
from api.model.responses import WiFiConnectionResponse, WiFiListResponse
from api.service.wifi_service import WiFiService

router = APIRouter()


@router.get(
    "/scan",
    response_model=WiFiListResponse,
    summary="Scan for WiFi networks",
    description="Scan and return a list of all available WiFi networks with signal strength and security info",
)
async def scan_wifi_networks(service: WiFiService = Depends(get_wifi_service)) -> WiFiListResponse:
    """
    Scan for available WiFi networks.

    Returns:
        WiFiListResponse: List of available WiFi networks.
    """
    return await service.scan_networks()


@router.post(
    "/connect",
    response_model=WiFiConnectionResponse,
    summary="Connect to WiFi network",
    description="Connect to a specified WiFi network with optional password",
)
async def connect_to_wifi(
    request: WiFiConnectRequest,
    service: WiFiService = Depends(get_wifi_service),
) -> WiFiConnectionResponse:
    """
    Connect to a WiFi network.

    Args:
        request: WiFi connection request containing SSID and optional password.

    Returns:
        WiFiConnectionResponse: Connection result with status and IP address.
    """
    return await service.connect_to_network(request.ssid, request.password)


@router.post(
    "/disconnect",
    summary="Disconnect from WiFi",
    description="Disconnect from the currently connected WiFi network",
)
async def disconnect_wifi(service: WiFiService = Depends(get_wifi_service)) -> dict:
    """
    Disconnect from current WiFi network.

    Returns:
        dict: Disconnection result.
    """
    return await service.disconnect_network()


@router.get(
    "/status",
    summary="Get network connection status",
    description="Get the current WiFi and Ethernet connection status with IP addresses",
)
async def get_wifi_status(service: WiFiService = Depends(get_wifi_service)) -> dict:
    """
    Get current network connection status (WiFi and Ethernet).

    Returns:
        dict: Current connection status information including:
            - wifi: WiFi connection details (connected, ssid, ip_address)
            - ethernet: Ethernet connection details (connected, device, ip_address)
            - connection_type: Primary connection type (wifi/ethernet/none)
    """
    current_ssid = service._get_current_ssid()
    wifi_ip = service._get_current_ip()
    ethernet_status = service._get_ethernet_status()

    # Determine primary connection type
    connection_type = "none"
    if current_ssid:
        connection_type = "wifi"
    elif ethernet_status["connected"]:
        connection_type = "ethernet"

    return {
        "wifi": {
            "connected": current_ssid is not None,
            "ssid": current_ssid,
            "ip_address": wifi_ip,
        },
        "ethernet": {
            "connected": ethernet_status["connected"],
            "device": ethernet_status["device"],
            "ip_address": ethernet_status["ip_address"],
        },
        "connection_type": connection_type,
    }
