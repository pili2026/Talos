import asyncio
import logging
import os
from asyncio.subprocess import Process
from pathlib import Path

from fastapi import HTTPException

from api.model.enum.wifi import SecurityType, SitePriorityMode
from api.model.enums import ResponseStatus
from api.model.wifi import (
    WiFiConnectRequest,
    WiFiConnectResponse,
    WiFiInterfaceInfo,
    WiFiInterfacesResponse,
    WiFiListResponse,
    WiFiNetwork,
    WiFiStatusInfo,
    WiFiStatusResponse,
    WpaNetworkRow,
    WpaStatus,
)
from api.model.wifi_config import WiFiConfig
from api.util.wifi_util import WiFiUtil

logger = logging.getLogger("WiFiService")


class WiFiService:
    """
    WiFi Management Service

    Backend: wpa_cli (wpa_supplicant)
    Thread-safe: Each network interface uses independent asyncio.Lock

    Priority System:
    - 5: Rescue SSIDs (highest priority for automatic fallback)
    - 4: Site networks (FIXED_4 mode)
    - 4,3,2,1,0: Site networks (DECREMENT mode, auto-assigned)

    Connection Behavior:
    - When connecting to any network, select_network disables all others
    - Rescue SSID remains in config but disabled during normal operation
    - Auto-fallback monitor (30s interval) detects disconnections
    - After 3 consecutive failures (90s), rescue SSID is re-enabled
    - wpa_supplicant automatically switches to highest priority available network

    Rescue SSID Mechanism:
    - Default: {"imaoffice1"}
    - Env: TALOS_WIFI_RESCUE_SSIDS="ssid1,ssid2"
    - Priority: Always 5 (highest)
    - Purpose: Automatic fallback when site network fails
    - Critical for remote device recovery

    Site Priority Modes:
    - FIXED_4: All site networks get priority 4 (< rescue priority)
    - DECREMENT: Auto-assign 4,3,2,1,0 based on usage (all < rescue priority)
    - Env: TALOS_WIFI_SITE_PRIORITY_MODE=fixed_4|decrement
    """

    RESCUE_PRIORITY = 5
    SITE_PRIORITY_FIXED = 4

    def __init__(
        self,
        config: WiFiConfig | None = None,
        allowed_ifnames: set[str] | None = None,
    ):
        """
        Initialize WiFi Service

        Args:
            config: WiFi configuration object; loads from env if None
            allowed_ifnames: Set of allowed interface names; auto-detects if None
        """
        self._config = config or WiFiConfig.from_env()
        self._allowed_ifnames = allowed_ifnames

        # Per-interface operation locks (prevent concurrent wpa_cli conflicts)
        self._operation_locks: dict[str, asyncio.Lock] = {}

        self._auto_fallback_enabled = os.getenv("TALOS_WIFI_AUTO_FALLBACK", "true").lower() == "true"
        self._fallback_check_interval_sec = int(os.getenv("TALOS_WIFI_FALLBACK_CHECK_INTERVAL", "10"))
        self._fallback_retry_threshold = int(os.getenv("TALOS_WIFI_FALLBACK_RETRY_THRESHOLD", "2"))
        self._connection_failures: dict[str, int] = {}

        logger.info(
            "[WiFiService] Initialized with config: default_ifname=%s, "
            "rescue_ssids=%s, priority_mode=%s, auto_fallback=%s",
            self._config.default_ifname,
            self._config.rescue_ssids,
            self._config.site_priority_mode.value,
            self._auto_fallback_enabled,
        )

        self._fallback_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()

    @property
    def default_ifname(self) -> str:
        """Default network interface name"""
        return self._config.default_ifname

    # -------------------------
    # Public APIs (per-call ifname)
    # -------------------------

    async def start_auto_fallback_monitor(self) -> None:
        """
        Enable and start the auto-fallback monitor task.

        This task periodically checks the WiFi connection status.
        """
        if not self._auto_fallback_enabled:
            logger.info("[WiFiService] Auto-fallback is disabled")
            return

        if self._fallback_task is not None:
            logger.warning("[WiFiService] Auto-fallback monitor already running")
            return

        logger.info("[WiFiService] Starting auto-fallback monitor")
        self._fallback_task = asyncio.create_task(self._auto_fallback_loop())

    async def stop_auto_fallback_monitor(self) -> None:
        """Stop the auto-fallback monitor task."""
        if self._fallback_task is None:
            logger.debug("[WiFiService] Auto-fallback monitor not running")
            return

        logger.info("[WiFiService] Stopping auto-fallback monitor")
        self._shutdown_event.set()

        try:
            await asyncio.wait_for(self._fallback_task, timeout=5.0)
            logger.info("[WiFiService] Auto-fallback monitor stopped gracefully")
        except asyncio.TimeoutError:
            logger.warning("[WiFiService] Auto-fallback monitor timeout, cancelling task")
            self._fallback_task.cancel()
            try:
                await self._fallback_task
            except asyncio.CancelledError:
                logger.info("[WiFiService] Auto-fallback monitor cancelled")
        finally:
            self._fallback_task = None

    async def get_status(self, ifname: str | None = None) -> WiFiStatusResponse:
        """
        Get current WiFi connection status.

        Args:
            ifname: Network interface name; defaults to the configured interface

        Returns:
            WiFiStatusResponse containing connection details
        """
        ifname: str = self._resolve_ifname(ifname)
        try:
            text: str = await self._run_wpa_cli(ifname, "status")
            wpa_status = WpaStatus.from_wpa_output(text)

            wifi_status_info = WiFiStatusInfo(
                interface=ifname,
                ssid=wpa_status.ssid,
                bssid=wpa_status.bssid,
                freq=wpa_status.freq,
                wpa_state=wpa_status.wpa_state,
                ip_address=wpa_status.ip_address,
                network_id=wpa_status.network_id,
                key_mgmt=wpa_status.key_mgmt,
                is_connected=wpa_status.is_connected,
            )
            return WiFiStatusResponse(status=ResponseStatus.SUCCESS, status_info=wifi_status_info)

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[WiFiService] get_status error on {ifname}: {e}", exc_info=True)
            return WiFiStatusResponse(
                status=ResponseStatus.ERROR,
                message="Unable to retrieve WiFi status",
                status_info=WiFiStatusInfo(interface=ifname, is_connected=False),
            )

    async def scan(self, ifname: str | None = None, group_by_ssid: bool = True) -> WiFiListResponse:
        """
        Scan for available WiFi networks.

        Args:
            ifname: Network interface name; defaults to the configured interface
            group_by_ssid: If True, return only the strongest AP per SSID

        Returns:
            WiFiListResponse containing scanned networks
        """
        ifname: str = self._resolve_ifname(ifname)
        try:
            # Trigger scan
            await self._run_wpa_cli(ifname, "scan")
            # Wait for scan completion (configurable)
            await asyncio.sleep(self._config.scan_wait_sec)

            # Get current connection status
            status_text: str = await self._run_wpa_cli(ifname, "status")
            wpa_status = WpaStatus.from_wpa_output(status_text)

            results_text: str = await self._run_wpa_cli(ifname, "scan_results")
            networks: list[WiFiNetwork] = WiFiUtil.parse_scan_results(
                results_text,
                current_ssid=wpa_status.ssid,
                current_bssid=wpa_status.bssid,
                group_by_ssid=group_by_ssid,
            )
            return WiFiListResponse(
                status=ResponseStatus.SUCCESS,
                interface=ifname,
                networks=networks,
                total_count=len(networks),
                current_ssid=wpa_status.ssid,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[WiFiService] scan error on {ifname}: {e}", exc_info=True)
            return WiFiListResponse(
                status=ResponseStatus.ERROR,
                message="Unable to scan WiFi networks",
                interface=ifname,
                networks=[],
                total_count=0,
                current_ssid=None,
            )

    async def connect(self, req: WiFiConnectRequest, ifname: str | None = None) -> WiFiConnectResponse:
        """
        Connect to a specified WiFi network.

        This operation:
        1. Validates request parameters
        2. Creates or updates wpa_supplicant network configuration
        3. Applies priority rules
        4. Selects and enables the target network
        5. Ensures rescue SSIDs remain enabled (if present)

        Args:
            req: WiFi connection request
            ifname: Network interface name; defaults to the configured interface

        Returns:
            WiFiConnectResponse containing connection result
        """
        ifname = self._resolve_ifname(ifname)

        # Ensure single operation per interface
        async with self._get_operation_lock(ifname):
            try:
                # Validate request (raises HTTPException on failure)
                WiFiUtil.validate_connect_request(req)

                # Retrieve existing networks
                networks = await self._list_networks(ifname)

                # Check whether rescue SSIDs exist (critical for remote safety)
                rescue_present: bool = WiFiUtil.has_any_ssid(networks, self._config.rescue_ssids)

                # Get or create network ID
                net_id = await self._get_or_create_network_id(ifname, req.ssid, networks)

                # Refresh network list (may have changed)
                networks = await self._list_networks(ifname)

                # Configure SSID, PSK, and security
                await self._set_network_ssid_psk_security(ifname, net_id, req)

                # Apply BSSID lock if specified
                applied_bssid = None
                bssid_locked = False
                if req.bssid:
                    await self._run_wpa_cli(ifname, "set_network", str(net_id), "bssid", req.bssid)
                    applied_bssid = req.bssid
                    bssid_locked = True

                # Apply priority
                applied_priority = await self._apply_priority(ifname, net_id, req.ssid, req.priority, networks)

                # Enable and select network
                # await self._run_wpa_cli(ifname, "enable_network", str(net_id))
                await self._run_wpa_cli(ifname, "select_network", str(net_id))

                # Persist configuration (best-effort with diagnostics)
                saved, save_error = await self._save_config_with_diagnostics(ifname, req.save_config)

                # Prepare response
                warnings: list[str] = []
                note = (
                    "Network switch initiated. Client connectivity may be interrupted; "
                    "poll GET /wifi/status to confirm connection state."
                )

                if not rescue_present:
                    warnings.append("RESCUE_SSID_MISSING")
                    note = (
                        "Network switch initiated. WARNING: No rescue SSID found in wpa_supplicant configuration. "
                        "Recovery may require manual intervention if site WiFi fails. "
                        "Poll GET /wifi/status to confirm connection state."
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
                # Validation errors propagate directly
                raise

            except Exception as e:
                logger.error(f"[WiFiService] connect error on {ifname}: {e}", exc_info=True)
                return WiFiConnectResponse(
                    status=ResponseStatus.ERROR,
                    interface=ifname,
                    message=f"Failed to initiate WiFi connection: {e}",
                    ssid=req.ssid,
                    accepted=False,
                )

    async def list_interfaces(self) -> WiFiInterfacesResponse:
        """
        List wireless network interfaces on the system.

        Returns:
            WiFiInterfacesResponse containing interface list and recommended default
        """
        try:
            interface_list: list[WiFiInterfaceInfo] = self._discover_wifi_interfaces()

            # Apply allowlist filter if configured
            if self._allowed_ifnames is not None:
                interface_list = [i for i in interface_list if i.ifname in self._allowed_ifnames]

            # Keep only wireless interfaces
            wireless = [i for i in interface_list if i.is_wireless]

            # Determine recommended interface
            recommended: str | None = None
            if any(i.ifname == self._config.default_ifname and i.is_wireless for i in wireless):
                recommended = self._config.default_ifname
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
                message="Unable to list WiFi interfaces",
                interfaces=[],
                total_count=0,
                recommended_ifname=None,
            )

    def _get_operation_lock(self, ifname: str) -> asyncio.Lock:
        """
        Get the operation lock for a given interface.

        Ensures that WiFi operations on the same interface are not executed concurrently,
        preventing wpa_cli state conflicts.
        """
        if ifname not in self._operation_locks:
            self._operation_locks[ifname] = asyncio.Lock()
        return self._operation_locks[ifname]

    def _discover_wifi_interfaces(self) -> list[WiFiInterfaceInfo]:
        """
        Discover network interfaces from /sys/class/net

        Returns:
            List of network interface info, sorted by default interface first, then by name
        """
        base = Path("/sys/class/net")
        if not base.exists():
            return []

        items: list[WiFiInterfaceInfo] = []

        for p in base.iterdir():
            ifname = p.name

            # Skip loopback
            if ifname == "lo":
                continue

            # Check if wireless (has wireless directory)
            is_wireless = (p / "wireless").exists()

            # Check interface status
            is_up = WiFiUtil.read_text(p / "operstate") == "up"

            # Read MAC address
            mac = WiFiUtil.read_text(p / "address") or None

            # Read driver name (best-effort)
            driver = None
            driver_link = p / "device" / "driver"
            if driver_link.exists():
                try:
                    driver = driver_link.resolve().name
                except Exception:
                    driver = None

            # Read PHY name (best-effort)
            phy = None
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
                    is_default=(ifname == self._config.default_ifname),
                )
            )

        # Sort: default interface first, then by name
        items.sort(key=lambda x: (not x.is_default, x.ifname))
        return items

    def _resolve_ifname(self, ifname: str | None) -> str:
        """
        Resolve and validate network interface name.

        Args:
            ifname: User-specified interface name; defaults to configured interface

        Returns:
            Resolved interface name

        Raises:
            HTTPException: If interface is not in allowlist
        """
        resolved = (ifname or "").strip() or self._config.default_ifname

        # Optional allow-list validation (recommended)
        if self._allowed_ifnames is not None and resolved not in self._allowed_ifnames:
            raise HTTPException(status_code=400, detail=f"Invalid ifname: {resolved}")
        return resolved

    async def _apply_priority(
        self,
        ifname: str,
        net_id: int,
        ssid: str,
        requested_priority: int | None,
        networks: list[WpaNetworkRow],
    ) -> int:
        """
        Apply network priority

        Priority decision logic:
        1. If rescue SSID, use RESCUE_PRIORITY (5)
        2. If user explicitly specified, use requested_priority
        3. Otherwise based on site_priority_mode:
           - FIXED_4: Use fixed value 4
           - DECREMENT: Auto-select unused priority (4,3,2,1,0)

        Args:
            ifname: Network interface name
            net_id: Network ID
            ssid: SSID
            requested_priority: User-requested priority (can be None)
            networks: Existing network list

        Returns:
            Actually applied priority value
        """
        if ssid in self._config.rescue_ssids:
            # Rescue SSID always uses highest priority
            priority = self.RESCUE_PRIORITY
        elif requested_priority is not None:
            # User explicitly specified
            priority = requested_priority
        else:
            # Based on configured mode
            if self._config.site_priority_mode == SitePriorityMode.FIXED_4:
                priority = self.SITE_PRIORITY_FIXED
            else:
                # DECREMENT mode: find used priorities, select unused max value
                used = await self._get_used_site_priorities(ifname, networks)
                priority = WiFiUtil.pick_site_priority_decrement(used)

        await self._run_wpa_cli(ifname, "set_network", str(net_id), "priority", str(priority))
        return priority

    async def _get_used_site_priorities(self, ifname: str, networks: list[WpaNetworkRow]) -> set[int]:
        """
        Get set of used site priorities (< RESCUE_PRIORITY)

        Args:
            ifname: Network interface name
            networks: Network list

        Returns:
            Set of used priorities
        """
        used: set[int] = set()
        for n in networks:
            try:
                p = await self._run_wpa_cli(ifname, "get_network", str(n.network_id), "priority")
                pv = WiFiUtil.to_int(p.strip())
                if pv is not None and pv < self.RESCUE_PRIORITY:
                    used.add(pv)
            except Exception:
                continue
        return used

    async def _ensure_rescue_priority_and_enabled(self, ifname: str) -> None:
        """
        Ensure rescue SSIDs maintain highest priority and remain enabled

        This method is executed after network switching to ensure rescue networks
        are not disabled or deprioritized.

        Args:
            ifname: Network interface name
        """
        network_list = await self._list_networks(ifname)
        for n in network_list:
            if n.ssid in self._config.rescue_ssids:
                await self._run_wpa_cli(ifname, "set_network", str(n.network_id), "priority", str(self.RESCUE_PRIORITY))
                await self._run_wpa_cli(ifname, "enable_network", str(n.network_id))

    async def _run_wpa_cli(self, ifname: str, *args: str, mask_password: bool = False) -> str:
        """
        Execute wpa_cli command

        Args:
            ifname: Network interface name
            *args: wpa_cli arguments
            mask_password: Whether to mask password in logs (for security)

        Returns:
            Command output

        Raises:
            RuntimeError: Command execution failed or timed out
        """
        cmd: list[str] = []
        if self._config.use_sudo:
            cmd.append("sudo")
        cmd += ["wpa_cli", "-i", ifname, *args]

        # Prepare safe command for logging (mask password)
        safe_cmd: list[str] = WiFiUtil.mask_sensitive_args(cmd) if mask_password else cmd

        process: Process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            out_b, err_b = await asyncio.wait_for(process.communicate(), timeout=self._config.timeout_sec)
        except asyncio.TimeoutError as e:
            process.kill()
            raise RuntimeError(f"wpa_cli timeout: {' '.join(safe_cmd)}") from e

        out = (out_b or b"").decode("utf-8", errors="ignore").strip()
        err = (err_b or b"").decode("utf-8", errors="ignore").strip()

        if process.returncode != 0:
            raise RuntimeError(f"wpa_cli failed (code={process.returncode}) " f"cmd={' '.join(safe_cmd)} err={err!r}")
        if out == "FAIL":
            raise RuntimeError(f"wpa_cli returned FAIL: {' '.join(safe_cmd)} err={err!r}")
        return out

    async def _list_networks(self, ifname: str) -> list[WpaNetworkRow]:
        """
        List configured networks in wpa_supplicant

        Args:
            ifname: Network interface name

        Returns:
            List of network configurations
        """
        out = await self._run_wpa_cli(ifname, "list_networks")
        lines = (out or "").splitlines()
        if len(lines) <= 1:
            return []

        row_list: list[WpaNetworkRow] = []
        for line in lines[1:]:  # Skip header line
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            nid = WiFiUtil.to_int(parts[0])
            if nid is None:
                continue
            ssid = parts[1].strip()
            bssid = parts[2].strip() if len(parts) >= 3 and parts[2].strip() else None
            flags = parts[3].strip() if len(parts) >= 4 and parts[3].strip() else None
            row_list.append(WpaNetworkRow(network_id=nid, ssid=ssid, bssid=bssid, flags=flags))
        return row_list

    async def _get_or_create_network_id(self, ifname: str, ssid: str, networks: list[WpaNetworkRow]) -> int:
        """
        Get or create network ID for specified SSID

        If the SSID already exists in configuration, return its ID; otherwise create new network and return new ID.

        Args:
            ifname: Network interface name
            ssid: Target SSID
            networks: Existing network list

        Returns:
            Network ID

        Raises:
            RuntimeError: Failed to create network
        """
        # Check if already exists
        for network in networks:
            if network.ssid == ssid:
                return network.network_id

        # Create new network
        command_output: str = await self._run_wpa_cli(ifname, "add_network")
        network_id: int | None = WiFiUtil.to_int(command_output.strip())
        if network_id is None:
            raise RuntimeError(f"add_network returned invalid id: {command_output!r}")
        return network_id

    async def _set_network_ssid_psk_security(self, ifname: str, net_id: int, req: WiFiConnectRequest) -> None:
        """
        Configure network SSID, password, and security

        Args:
            ifname: Network interface name
            net_id: Network ID
            req: Connection request (contains SSID, password, security)
        """
        # Set SSID
        await self._run_wpa_cli(ifname, "set_network", str(net_id), "ssid", f'"{req.ssid}"')

        if req.security == SecurityType.OPEN:
            # Open network: no authentication
            await self._run_wpa_cli(ifname, "set_network", str(net_id), "key_mgmt", "NONE")
            # Clear any existing password (best-effort)
            try:
                await self._run_wpa_cli(ifname, "set_network", str(net_id), "psk", '""')
            except Exception:
                pass
            return

        # Encrypted network: set password (use masking to avoid log leaks)
        await self._run_wpa_cli(ifname, "set_network", str(net_id), "key_mgmt", "WPA-PSK")
        await self._run_wpa_cli(ifname, "set_network", str(net_id), "psk", f'"{req.psk}"', mask_password=True)

    async def _save_config_with_diagnostics(self, ifname: str, enabled: bool) -> tuple[bool, str | None]:
        """
        Save wpa_supplicant configuration (with diagnostics)

        Note: This method uses sudo wpa_cli, so it has root permissions.
        Do not check file permissions with os.access() as it checks current process permissions.

        Args:
            ifname: Network interface name
            enabled: Whether to save

        Returns:
            (success, error_message)
        """
        if not enabled:
            return False, None

        try:
            logger.debug(f"[WiFiService] Attempting save_config on {ifname}")
            out = await self._run_wpa_cli(ifname, "save_config")

            if out.strip().upper() == "OK":
                logger.info(f"[WiFiService] Configuration saved successfully on {ifname}")
                return True, None

            # save_config returned non-OK response
            error_msg = f"save_config returned: {out!r}"

            # Provide hints for common issues
            if "fail" in out.lower():
                # Check common configuration issues
                try:
                    # Try to detect if update_config is disabled
                    config_paths = [
                        f"/etc/wpa_supplicant/wpa_supplicant-{ifname}.conf",
                        "/etc/wpa_supplicant/wpa_supplicant.conf",
                    ]

                    for config_path in config_paths:
                        if Path(config_path).exists():
                            error_msg += f" (Check if update_config=1 in {config_path})"
                            break
                except Exception:
                    pass

            logger.warning(f"[WiFiService] {error_msg}")
            return False, error_msg

        except RuntimeError as e:
            error_str = str(e)
            logger.error(f"[WiFiService] save_config failed on {ifname}: {error_str}")

            # Check if it's a real read-only filesystem issue
            if "read-only" in error_str.lower() or "permission denied" in error_str.lower():
                return False, "Unable to save configuration. File system may be read-only or permissions issue."

            return False, f"Failed to persist configuration: {error_str}"

        except Exception as e:
            logger.error(f"[WiFiService] save_config exception on {ifname}: {e}", exc_info=True)
            return False, f"Unexpected error while saving configuration: {e}"

    async def _trigger_rescue_fallback(self, ifname: str) -> None:
        """
        Trigger fallback to rescue SSID

        Strategy:
        1. Enable rescue SSID (priority=5)
        2. wpa_supplicant will automatically select the network with the highest priority and is available
        3. Since rescue SSID priority > site networks, it will automatically switch
        """
        async with self._get_operation_lock(ifname):
            try:
                logger.info(f"[WiFiService] Initiating rescue fallback on {ifname}")

                # Get network list
                networks = await self._list_networks(ifname)

                # Find the rescue SSID
                rescue_net_id = None
                rescue_ssid = None
                for n in networks:
                    if n.ssid in self._config.rescue_ssids:
                        rescue_net_id = n.network_id
                        rescue_ssid = n.ssid
                        break

                if rescue_net_id is None:
                    logger.error(
                        f"[WiFiService] CRITICAL: No rescue SSID found in config on {ifname}! "
                        f"Manual intervention required."
                    )
                    return

                # Ensure rescue SSID priority is correct (should already be 5)
                await self._run_wpa_cli(
                    ifname, "set_network", str(rescue_net_id), "priority", str(self.RESCUE_PRIORITY)
                )

                # wpa_supplicant will automatically select the network with the highest priority and is available
                await self._run_wpa_cli(ifname, "enable_network", str(rescue_net_id))

                # Trigger re-evaluation (optional, some versions of wpa_supplicant require it)
                await self._run_wpa_cli(ifname, "reassociate")

                # Save configuration
                try:
                    await self._run_wpa_cli(ifname, "save_config")
                except Exception as e:
                    logger.warning(f"[WiFiService] Failed to save config during fallback: {e}")

                logger.info(
                    f"[WiFiService] Rescue fallback initiated on {ifname}, "
                    f"enabled {rescue_ssid} (net_id={rescue_net_id}, priority={self.RESCUE_PRIORITY})"
                )

            except Exception as e:
                logger.error(f"[WiFiService] Rescue fallback failed on {ifname}: {e}", exc_info=True)

    async def _check_and_fallback(self, ifname: str) -> None:
        """Check connection status and trigger fallback if needed."""
        resolved: str | None = self._try_resolve_ifname(ifname)
        if resolved is None:
            # Wired-only / interface not allowed: not an error for background watchdog
            logger.debug(f"[WiFiService] Skip fallback check: invalid/unavailable ifname={ifname!r}")
            return

        try:
            status_response = await self.get_status(resolved)
            status = status_response.status_info

            if status.is_connected:
                current_ssid = status.ssid

                if resolved in self._connection_failures and self._connection_failures[resolved] > 0:
                    logger.info(
                        f"[WiFiService] Connection restored on {resolved} (SSID: {current_ssid}), "
                        f"resetting failure count"
                    )
                    self._connection_failures[resolved] = 0

                if current_ssid in self._config.rescue_ssids:
                    logger.debug(f"[WiFiService] Currently on rescue SSID: {current_ssid}")

                return

            self._connection_failures[resolved] = self._connection_failures.get(resolved, 0) + 1
            failure_count = self._connection_failures[resolved]

            logger.warning(
                f"[WiFiService] Connection failure detected on {resolved} "
                f"(count: {failure_count}/{self._fallback_retry_threshold})"
            )

            if failure_count >= self._fallback_retry_threshold:
                should_fallback = await self._should_trigger_fallback(resolved)

                if should_fallback:
                    logger.error(
                        f"[WiFiService] Connection failure threshold reached on {resolved}. "
                        f"Triggering fallback to rescue SSID."
                    )
                    await self._trigger_rescue_fallback(resolved)
                else:
                    logger.error(
                        f"[WiFiService] Rescue SSID already enabled but still disconnected on {resolved}. "
                        f"Both networks may be unavailable."
                    )

                self._connection_failures[resolved] = 0

        except Exception as e:
            logger.error(f"[WiFiService] Error in _check_and_fallback for {resolved}: {e}", exc_info=True)

    async def _should_trigger_fallback(self, ifname: str) -> bool:
        """
        Check if fallback to rescue SSID should be triggered.

        Returns:
            True: Should trigger fallback (rescue SSID is currently disabled)
            False: Should not trigger (rescue SSID is enabled but still disconnected, indicating both networks are unavailable)
        """
        networks = await self._list_networks(ifname)

        for n in networks:
            if n.ssid in self._config.rescue_ssids:
                is_disabled = n.flags and "DISABLED" in n.flags
                return is_disabled
        return True

    async def _auto_fallback_loop(self) -> None:
        """Auto fallback monitor loop."""
        while not self._shutdown_event.is_set():
            try:
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=self._fallback_check_interval_sec)
                    break
                except asyncio.TimeoutError:
                    pass

                await self._check_and_fallback(self._config.default_ifname)

            except Exception as e:
                logger.error(f"[WiFiService] Auto-fallback loop error: {e}", exc_info=True)

        logger.info("[WiFiService] Auto-fallback monitor stopped")

    def _try_resolve_ifname(self, ifname: str | None) -> str | None:
        """
        Internal resolver for background tasks.

        Returns:
            Resolved ifname if valid/allowed; otherwise None (skip silently).
        """
        resolved = (ifname or "").strip() or self._config.default_ifname

        if self._allowed_ifnames is not None and resolved not in self._allowed_ifnames:
            return None

        return resolved

    @classmethod
    def create_with_auto_discovery(cls) -> "WiFiService":
        """Factory method with auto-discovery."""
        config = WiFiConfig.from_env()
        allowed_ifnames = WiFiUtil.discover_wireless_interfaces()
        logger.info(
            "[WiFiService] Created: default_ifname=%s, allowed_ifnames=%s",
            config.default_ifname,
            allowed_ifnames,
        )
        return cls(config=config, allowed_ifnames=allowed_ifnames)
