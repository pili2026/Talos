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
    summary="Get WiFi connection status",
    description="Get the current WiFi connection status and connected network information",
)
async def get_wifi_status(service: WiFiService = Depends(get_wifi_service)) -> dict:
    """
    Get current WiFi connection status.

    Returns:
        dict: Current connection status information.
    """
    current_ssid = service._get_current_ssid()
    current_ip = service._get_current_ip()

    return {
        "connected": current_ssid is not None,
        "ssid": current_ssid,
        "ip_address": current_ip,
    }
