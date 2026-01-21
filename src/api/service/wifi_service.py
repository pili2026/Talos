import asyncio
from dataclasses import dataclass
import logging
import os

from pathlib import Path
import string
from typing import Iterable

from fastapi import HTTPException, status

from api.model.enum.wifi import SecurityType, SitePriorityMode
from api.model.enums import ResponseStatus
from api.model.wifi import (
    WiFiConnectRequest,
    WiFiConnectResponse,
    WiFiInterfaceInfo,
    WiFiInterfacesResponse,
    WiFiListResponse,
    WiFiNetwork,
    WiFiStatusResponse,
    WiFiStatusInfo,
)

logger = logging.getLogger("WiFiService")


@dataclass(frozen=True)
class WpaNetworkRow:
    network_id: int
    ssid: str
    bssid: str | None
    flags: str | None


class WiFiService:
    """
    Backend: wpa_cli (wpa_supplicant)
    """

    RESCUE_SSIDS = {"imaoffice1"}
    RESCUE_PRIORITY = 5
    SITE_PRIORITY_FIXED = 4

    def __init__(
        self,
        default_ifname: str = "wlan0",
        use_sudo: bool = True,
        timeout_sec: float = 3.0,
        allowed_ifnames: set[str] | None = None,
    ):
        self._default_ifname = default_ifname
        self._use_sudo = use_sudo
        self._timeout_sec = float(timeout_sec)

        # Optional allow-list from router (recommended)
        self._allowed_ifnames = allowed_ifnames

        rescue_ssids_env: str = os.getenv("TALOS_WIFI_RESCUE_SSIDS", "").strip()
        env_ssids: set[str] = {s.strip() for s in rescue_ssids_env.split(",") if s.strip()}
        self._rescue_ssids: set[str] = set(self.RESCUE_SSIDS) | env_ssids

        mode: str = os.getenv("TALOS_WIFI_SITE_PRIORITY_MODE", SitePriorityMode.DECREMENT.value).strip().lower()
        self._site_priority_mode = (
            SitePriorityMode(mode) if mode in {m.value for m in SitePriorityMode} else SitePriorityMode.DECREMENT
        )

    @property
    def default_ifname(self) -> str:
        return self._default_ifname

    # -------------------------
    # Public APIs (per-call ifname)
    # -------------------------

    async def get_status(self, ifname: str | None = None) -> WiFiStatusResponse:
        ifname = self._resolve_ifname(ifname)
        try:
            text = await self._run_wpa_cli(ifname, "status")
            data = self._parse_key_value(text)

            ssid = data.get("ssid")
            bssid = data.get("bssid")
            freq = self._to_int(data.get("freq"))
            wpa_state = data.get("wpa_state")
            ip_address = data.get("ip_address")
            network_id = self._to_int(data.get("id"))
            key_mgmt = data.get("key_mgmt")

            is_connected = (wpa_state == "COMPLETED") and bool(ssid) and bool(ip_address)

            info = WiFiStatusInfo(
                interface=ifname,
                ssid=ssid,
                bssid=bssid,
                freq=freq,
                wpa_state=wpa_state,
                ip_address=ip_address,
                network_id=network_id,
                key_mgmt=key_mgmt,
                is_connected=is_connected,
            )
            return WiFiStatusResponse(status=ResponseStatus.SUCCESS, status_info=info)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[WiFiService] get_status error: {e}", exc_info=True)
            return WiFiStatusResponse(
                status=ResponseStatus.ERROR,
                message="Failed to get Wi-Fi status",
                status_info=WiFiStatusInfo(interface=ifname, is_connected=False),
            )

    async def scan(self, ifname: str | None = None, group_by_ssid: bool = True) -> WiFiListResponse:
        ifname = self._resolve_ifname(ifname)
        try:
            await self._run_wpa_cli(ifname, "scan")
            await asyncio.sleep(1.0)

            status_text = await self._run_wpa_cli(ifname, "status")
            wifi_status = self._parse_key_value(status_text)
            current_ssid = wifi_status.get("ssid")
            current_bssid = wifi_status.get("bssid")

            results_text = await self._run_wpa_cli(ifname, "scan_results")
            networks = self._parse_scan_results(
                results_text,
                current_ssid=current_ssid,
                current_bssid=current_bssid,
                group_by_ssid=group_by_ssid,
            )

            return WiFiListResponse(
                status=ResponseStatus.SUCCESS,
                interface=ifname,
                networks=networks,
                total_count=len(networks),
                current_ssid=current_ssid,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[WiFiService] scan error: {e}", exc_info=True)
            return WiFiListResponse(
                status=ResponseStatus.ERROR,
                message="Failed to scan Wi-Fi networks",
                networks=[],
                total_count=0,
                current_ssid=None,
            )

    async def connect(self, req: WiFiConnectRequest, ifname: str | None = None) -> WiFiConnectResponse:
        ifname = self._resolve_ifname(ifname)

        try:
            networks = await self._list_networks(ifname)

            rescue_present: bool = self._has_any_ssid(networks, self._rescue_ssids)

            # Validate psk vs security
            if req.security == SecurityType.OPEN and req.psk:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OPEN network must not include psk")

            if req.security != SecurityType.OPEN and not req.psk:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=f"{req.security.value} network requires psk"
                )

            net_id = await self._get_or_create_network_id(ifname, req.ssid, networks)
            networks = await self._list_networks(ifname)

            # Apply security first
            await self._set_network_ssid_psk_security(ifname, net_id, req)

            applied_bssid = None
            bssid_locked = False
            if req.bssid:
                await self._run_wpa_cli(ifname, "set_network", str(net_id), "bssid", req.bssid)
                applied_bssid = req.bssid
                bssid_locked = True

            applied_priority = await self._apply_priority(ifname, net_id, req.ssid, req.priority, networks)

            await self._run_wpa_cli(ifname, "enable_network", str(net_id))
            await self._run_wpa_cli(ifname, "select_network", str(net_id))

            # Guard rail (only if present)
            if rescue_present:
                await self._ensure_rescue_priority_and_enabled(ifname)

            saved, save_error = await self._save_config_best_effort(ifname, req.save_config)

            warnings: list[str] = []
            note = "Switch initiated. Client connection may drop; poll GET /wifi/status to confirm."

            if not rescue_present:
                warnings.append("RESCUE_SSID_MISSING")
                note = (
                    "Switch initiated. WARNING: rescue SSID not found in wpa_supplicant config. "
                    "If site Wi-Fi fails, recovery may require manual provisioning. "
                    "Poll GET /wifi/status to confirm."
                )

            return WiFiConnectResponse(
                status=ResponseStatus.SUCCESS,
                interface=ifname,
                ssid=req.ssid,
                accepted=True,
                applied_network_id=net_id,
                applied_priority=applied_priority,
                applied_bssid=applied_bssid,
                bssid_locked=bssid_locked,
                rescue_present=rescue_present,
                warnings=warnings,
                saved=saved,
                save_error=save_error,
                note=note,
                recommended_poll_interval_ms=1000,
                recommended_timeout_ms=30000,
            )
        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"[WiFiService] connect error: {e}", exc_info=True)
            return WiFiConnectResponse(
                status=ResponseStatus.ERROR,
                interface=ifname,
                message="Failed to initiate Wi-Fi connect",
                ssid=req.ssid,
                accepted=False,
            )

    async def list_interfaces(self) -> WiFiInterfacesResponse:
        try:
            interface_list: list[WiFiInterfaceInfo] = self._discover_wifi_interfaces()

            if self._allowed_ifnames is not None:
                interface_list = [i for i in interface_list if i.ifname in self._allowed_ifnames]

            wireless: list[WiFiInterfaceInfo] = [i for i in interface_list if i.is_wireless]

            recommended: str | None = None

            # prefer explicit default_ifname if it exists and is wireless
            if any(i.ifname == self._default_ifname and i.is_wireless for i in wireless):
                recommended = self._default_ifname
            elif wireless:
                recommended = wireless[0].ifname

            return WiFiInterfacesResponse(
                status=ResponseStatus.SUCCESS,
                interfaces=wireless,
                total_count=len(wireless),
                recommended_ifname=recommended,
            )

        except Exception as e:
            logger.error(f"[WiFiService] list_interfaces error: {e}", exc_info=True)
            return WiFiInterfacesResponse(
                status=ResponseStatus.ERROR,
                message="Failed to list Wi-Fi interfaces",
                interfaces=[],
                total_count=0,
                recommended_ifname=None,
            )

    # -------------------------
    # Internal helpers
    # -------------------------

    def _discover_wifi_interfaces(self) -> list[WiFiInterfaceInfo]:
        base = Path("/sys/class/net")
        if not base.exists():
            return []

        items: list[WiFiInterfaceInfo] = []

        for p in base.iterdir():
            ifname = p.name

            if ifname == "lo":
                continue

            is_wireless = (p / "wireless").exists()
            is_up = self._read_text(p / "operstate") == "up"
            mac = self._read_text(p / "address") or None

            driver = None
            driver_link = p / "device" / "driver"
            if driver_link.exists():
                try:
                    driver = driver_link.resolve().name
                except Exception:
                    driver = None

            phy = None
            # best-effort: Some system is /sys/class/net/wlan0/phy80211
            phy_link = p / "phy80211"
            if phy_link.exists():
                try:
                    phy = phy_link.resolve().name
                except Exception:
                    phy = None

            items.append(
                WiFiInterfaceInfo(
                    ifname=ifname,
                    is_wireless=is_wireless,
                    is_up=is_up,
                    mac=mac,
                    driver=driver,
                    phy=phy,
                    is_default=(ifname == self._default_ifname),
                )
            )

        items.sort(key=lambda x: (not x.is_default, x.ifname))
        return items

    @staticmethod
    def _read_text(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            return ""

    def _resolve_ifname(self, ifname: str | None) -> str:
        resolved = (ifname or "").strip() or self._default_ifname
        # optional allow-list validation (recommended)
        if self._allowed_ifnames is not None and resolved not in self._allowed_ifnames:
            raise HTTPException(status_code=400, detail=f"Invalid ifname: {resolved}")
        return resolved

    async def _run_wpa_cli(self, ifname: str, *args: str) -> str:
        cmd: list[str] = []
        if self._use_sudo:
            cmd.append("sudo")
        cmd += ["wpa_cli", "-i", ifname, *args]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=self._timeout_sec)
        except asyncio.TimeoutError as e:
            proc.kill()
            raise RuntimeError(f"wpa_cli timeout: {' '.join(cmd)}") from e

        out = (out_b or b"").decode("utf-8", errors="ignore").strip()
        err = (err_b or b"").decode("utf-8", errors="ignore").strip()

        if proc.returncode != 0:
            raise RuntimeError(f"wpa_cli failed (code={proc.returncode}) out={out!r} err={err!r}")
        if out == "FAIL":
            raise RuntimeError(f"wpa_cli returned FAIL: {' '.join(cmd)} err={err!r}")
        return out

    async def _list_networks(self, ifname: str) -> list[WpaNetworkRow]:
        out = await self._run_wpa_cli(ifname, "list_networks")
        lines = (out or "").splitlines()
        if len(lines) <= 1:
            return []

        rows: list[WpaNetworkRow] = []
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            nid = self._to_int(parts[0])
            if nid is None:
                continue
            ssid = parts[1].strip()
            bssid = parts[2].strip() if len(parts) >= 3 and parts[2].strip() else None
            flags = parts[3].strip() if len(parts) >= 4 and parts[3].strip() else None
            rows.append(WpaNetworkRow(network_id=nid, ssid=ssid, bssid=bssid, flags=flags))
        return rows

    async def _get_or_create_network_id(self, ifname: str, ssid: str, networks: list[WpaNetworkRow]) -> int:
        for n in networks:
            if n.ssid == ssid:
                return n.network_id
        out = await self._run_wpa_cli(ifname, "add_network")
        nid = self._to_int(out.strip())
        if nid is None:
            raise RuntimeError(f"add_network returned invalid id: {out!r}")
        return nid

    async def _set_network_ssid_psk_security(self, ifname: str, net_id: int, req: WiFiConnectRequest) -> None:
        await self._run_wpa_cli(ifname, "set_network", str(net_id), "ssid", f'"{req.ssid}"')

        if req.security == SecurityType.OPEN:
            await self._run_wpa_cli(ifname, "set_network", str(net_id), "key_mgmt", "NONE")
            try:
                await self._run_wpa_cli(ifname, "set_network", str(net_id), "psk", '""')
            except Exception:
                pass
            return

        await self._run_wpa_cli(ifname, "set_network", str(net_id), "key_mgmt", "WPA-PSK")
        await self._run_wpa_cli(ifname, "set_network", str(net_id), "psk", f'"{req.psk}"')

    async def _apply_priority(
        self,
        ifname: str,
        net_id: int,
        ssid: str,
        requested_priority: int | None,
        networks: list[WpaNetworkRow],
    ) -> int:
        if ssid in self._rescue_ssids:
            priority = self.RESCUE_PRIORITY
        elif requested_priority is not None:
            priority = requested_priority
        else:
            if self._site_priority_mode == SitePriorityMode.FIXED_4:
                priority = self.SITE_PRIORITY_FIXED
            else:
                used = await self._get_used_site_priorities(ifname, networks)
                priority = self._pick_site_priority_decrement(used)

        await self._run_wpa_cli(ifname, "set_network", str(net_id), "priority", str(priority))
        return priority

    async def _get_used_site_priorities(self, ifname: str, networks: list[WpaNetworkRow]) -> set[int]:
        used: set[int] = set()
        for n in networks:
            try:
                p = await self._run_wpa_cli(ifname, "get_network", str(n.network_id), "priority")
                pv = self._to_int(p.strip())
                if pv is not None and pv < self.RESCUE_PRIORITY:
                    used.add(pv)
            except Exception:
                continue
        return used

    async def _ensure_rescue_priority_and_enabled(self, ifname: str) -> None:
        network_list = await self._list_networks(ifname)
        for n in network_list:
            if n.ssid in self._rescue_ssids:
                await self._run_wpa_cli(ifname, "set_network", str(n.network_id), "priority", str(self.RESCUE_PRIORITY))
                await self._run_wpa_cli(ifname, "enable_network", str(n.network_id))

    async def _save_config_best_effort(self, ifname: str, enabled: bool) -> tuple[bool, str | None]:
        if not enabled:
            return False, None
        try:
            out = await self._run_wpa_cli(ifname, "save_config")
            if out.strip().upper() == "OK":
                return True, None
            return False, f"save_config returned: {out!r}"
        except Exception as e:
            logger.warning(f"[WiFiService] save_config failed (best-effort): {e}")
            return False, str(e)

    def _parse_scan_results(
            self,
            text: str,
            *,
            current_ssid: str | None,
            current_bssid: str | None,
            group_by_ssid: bool = True,
        ) -> list[WiFiNetwork]:
            lines: list[str] = (text or "").splitlines()
            if len(lines) <= 1:
                return []

            rows: list[str] = lines[1:]
            all_item_list: list[WiFiNetwork] = []

            for raw_line in rows:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue

                parts = raw_line.split("\t")
                if len(parts) < 4:
                    parts = raw_line.split()

                if len(parts) < 4:
                    continue

                bssid = parts[0].strip()
                freq = self._to_int(parts[1].strip()) if len(parts) >= 2 else None
                signal_dbm = self._to_int(parts[2].strip()) if len(parts) >= 3 else None
                if signal_dbm is None:
                    signal_dbm = -100

                flags = parts[3].strip() if len(parts) >= 4 else ""
                raw_ssid = "\t".join(parts[4:]).strip() if len(parts) >= 5 else ""

                display_ssid, is_valid, invalid_reason = self._sanitize_ssid(raw_ssid)

                security = SecurityType.from_wpa_flags(flags)
                signal_strength = self._dbm_to_percent(int(signal_dbm))

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

            # stable sort: in_use first, then stronger signal
            all_item_list.sort(key=lambda x: (not x.in_use, -x.signal_strength))

            if not group_by_ssid:
                return all_item_list

            # group_by_ssid = True: keep best AP per display SSID
            best_by_ssid: dict[str, WiFiNetwork] = {}
            for item in all_item_list:
                key = item.ssid  # display ssid key
                existing = best_by_ssid.get(key)
                if existing is None:
                    best_by_ssid[key] = item
                    continue

                if (not existing.in_use and item.in_use) or (
                    item.in_use == existing.in_use and item.signal_strength > existing.signal_strength
                ):
                    best_by_ssid[key] = item

            grouped = list(best_by_ssid.values())
            grouped.sort(key=lambda x: (not x.in_use, -x.signal_strength))
            return grouped


    @staticmethod
    def _pick_site_priority_decrement(used: set[int]) -> int:
        for p in [4, 3, 2, 1, 0]:
            if p not in used:
                return p
        return 0

    @staticmethod
    def _parse_key_value(text: str) -> dict[str, str]:
        data: dict[str, str] = {}
        for line in (text or "").splitlines():
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
        return data

    @staticmethod
    def _to_int(v: str | None) -> int | None:
        if v is None:
            return None
        try:
            return int(v)
        except Exception:
            return None

    @staticmethod
    def _sanitize_ssid(raw: str) -> tuple[str, bool, str | None]:
        if raw is None:
            return "(Hidden SSID)", True, None

        raw_str = raw.strip()
        if not raw_str:
            return "(Hidden SSID)", True, None

        if "\\x00" in raw_str.lower():
            return "(Invalid SSID)", False, "Contains null-byte pattern (\\x00)"

        if len(raw_str) > 32:
            return "(Invalid SSID)", False, "SSID length > 32"

        non_printable = [ch for ch in raw_str if (not ch.isprintable()) or (ch in "\r\n\t")]
        if non_printable:
            return "(Invalid SSID)", False, "Contains non-printable/control characters"

        if all(ch in string.punctuation for ch in raw_str):
            return "(Invalid SSID)", False, "SSID contains only punctuation"
        return raw_str, True, None

    @staticmethod
    def _dbm_to_percent(dbm: int) -> int:
        if dbm >= -30:
            return 100
        if dbm <= -90:
            return 0
        return int((dbm + 90) * (100 / 60))

    @staticmethod
    def _has_any_ssid(networks: list[WpaNetworkRow], ssids: Iterable[str]) -> bool:
        ssid_set = set(ssids)
        return any(n.ssid in ssid_set for n in networks)
