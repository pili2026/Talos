from fastapi import APIRouter, Depends, Query

from api.dependency import get_wifi_service
from api.model.wifi import (
    WiFiConnectRequest,
    WiFiConnectResponse,
    WiFiInterfacesResponse,
    WiFiListResponse,
    WiFiStatusResponse,
)
from api.service.wifi_service import WiFiService


router = APIRouter()


@router.get("/interfaces", response_model=WiFiInterfacesResponse, summary="List Wi-Fi interfaces")
async def wifi_interfaces(
    wifi_service: WiFiService = Depends(get_wifi_service),
) -> WiFiInterfacesResponse:
    return await wifi_service.list_interfaces()


@router.get("/status", response_model=WiFiStatusResponse, summary="Get current Wi-Fi status")
async def wifi_status(
    ifname: str | None = Query(default=None, description="Wi-Fi interface name (e.g., wlan0, wlan1)"),
    wifi_service: WiFiService = Depends(get_wifi_service),
) -> WiFiStatusResponse:
    return await wifi_service.get_status(ifname=ifname)


@router.get("/scan", response_model=WiFiListResponse, summary="Scan available Wi-Fi networks")
async def wifi_scan(
    ifname: str | None = Query(default=None, description="Wi-Fi interface name (e.g., wlan0, wlan1)"),
    group_by_ssid: bool = Query(default=True, description="Return best AP per SSID"),
    wifi_service: WiFiService = Depends(get_wifi_service),
) -> WiFiListResponse:
    return await wifi_service.scan(ifname=ifname, group_by_ssid=group_by_ssid)


@router.post("/connect", response_model=WiFiConnectResponse, summary="Connect to a Wi-Fi network")
async def wifi_connect(
    req: WiFiConnectRequest,
    ifname: str | None = Query(default=None, description="Wi-Fi interface name (e.g., wlan0, wlan1)"),
    wifi_service: WiFiService = Depends(get_wifi_service),
) -> WiFiConnectResponse:
    return await wifi_service.connect(req, ifname=ifname)
