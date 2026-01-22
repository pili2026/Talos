"""
System Provisioning Service

Manages site-specific system configuration:
- Hostname configuration
- Reverse SSH port configuration (connectserver.service)

Design principles:
- System files are the source of truth
- system_config.yaml provides fallback values
- Follows WiFiService pattern for sudo handling
"""

import asyncio
import logging
import re
import shutil
from asyncio.subprocess import Process
from pathlib import Path

from api.model.provision import ProvisionCurrentConfig, ProvisionRebootResult, ProvisionSetConfigResult
from api.model.provision_config import ProvisionConfig
from core.schema.system_config_schema import SystemConfig

logger = logging.getLogger("ProvisionService")


class ProvisionService:
    """
    System provisioning service for site configuration

    Capabilities:
    - Read current hostname and reverse SSH port
    - Update hostname (requires reboot to take effect)
    - Update reverse SSH port (restarts connectserver.service)
    - Validates all inputs before modification
    """

    SERVICE_FILE_PATH = Path("/etc/systemd/system/connectserver.service")
    HOSTNAME_FILE_PATH = Path("/etc/hostname")
    HOSTS_FILE_PATH = Path("/etc/hosts")

    def __init__(
        self,
        config: ProvisionConfig | None = None,
        system_config: SystemConfig | None = None,
    ):
        """
        Initialize provisioning service

        Args:
            config: Provisioning configuration; loads from env if None
            system_config: System configuration object; loads from YAML if None
        """
        self._config = config or ProvisionConfig.from_env()
        self._system_config = system_config

        self._lock = asyncio.Lock()

        if self._system_config is None:
            logger.warning("[ProvisionService] system_config not provided, " "fallback port will default to 8600")

        logger.info(
            "[ProvisionService] Initialized with use_sudo=%s, timeout=%s",
            self._config.use_sudo,
            self._config.timeout_sec,
        )

    # ========================================
    # Public API
    # ========================================

    def get_current_config(self) -> ProvisionCurrentConfig:
        """
        Get current system configuration

        Returns:
            ProvisionCurrentConfig with hostname, reverse_port, and port_source
        """
        hostname: str = self._read_hostname()
        port, port_source = self._read_reverse_port()

        return ProvisionCurrentConfig(
            hostname=hostname,
            reverse_port=port,
            port_source=port_source,
        )

    async def set_config(self, hostname: str, reverse_port: int) -> ProvisionSetConfigResult:
        """
        Update system configuration

        Steps:
        1. Validate inputs
        2. Update hostname (hostnamectl + /etc/hosts)
        3. Update reverse SSH port (connectserver.service)
        4. Reload and restart service

        Args:
            hostname: New hostname (11 alphanumeric characters)
            reverse_port: New reverse SSH port (1024-65535)

        Returns:
            ProvisionSetConfigResult with operation details

        Raises:
            ValueError: Invalid input
            RuntimeError: System command failed
        """
        async with self._lock:
            # Validate inputs
            self._validate_hostname(hostname)
            self._validate_port(reverse_port)

            changes = []

            try:
                # Update hostname
                current_hostname: str = self._read_hostname()
                if current_hostname != hostname:
                    await self._set_hostname(hostname)
                    await self._update_hosts_file(hostname)
                    changes.append("hostname")
                    logger.info(f"Hostname updated: {current_hostname} → {hostname}")
                else:
                    logger.info(f"Hostname unchanged: {hostname}")

                # Update reverse port
                current_port, _ = self._read_reverse_port()
                if current_port != reverse_port:
                    await self._update_service_port(reverse_port)
                    await self._reload_and_restart_service()
                    changes.append("reverse_port")
                    logger.info(f"Reverse port updated: {current_port} → {reverse_port}")
                else:
                    logger.info(f"Reverse port unchanged: {reverse_port}")

                message = "Configuration updated successfully"
                if not changes:
                    message = "No changes needed (configuration already matches)"

                return ProvisionSetConfigResult(
                    success=True,
                    requires_reboot="hostname" in changes,
                    changes=changes,
                    message=message,
                )

            except Exception as e:
                logger.error(f"Failed to update configuration: {e}", exc_info=True)
                raise

    async def trigger_reboot(self) -> ProvisionRebootResult:
        """
        Trigger system reboot

        Returns:
            ProvisionRebootResult with operation status
        """
        try:
            logger.warning("System reboot triggered")
            await self._run_command("reboot")
            return ProvisionRebootResult(
                success=True,
                message="System reboot initiated",
            )
        except Exception as e:
            logger.error(f"Failed to trigger reboot: {e}", exc_info=True)
            raise

    # ========================================
    # Hostname Operations
    # ========================================

    def _read_hostname(self) -> str:
        """
        Read current hostname from /etc/hostname

        Returns:
            Current hostname string
        """
        if not self.HOSTNAME_FILE_PATH.exists():
            logger.warning("HOSTNAME_FILE_PATH does not exist, returning unknown")
            return "unknown"

        hostname: str = self.HOSTNAME_FILE_PATH.read_text().strip()
        return hostname

    async def _set_hostname(self, hostname: str) -> None:
        """
        Set system hostname using hostnamectl

        Args:
            hostname: New hostname
        """
        await self._run_command("hostnamectl", "set-hostname", hostname)
        logger.info(f"Executed: hostnamectl set-hostname {hostname}")

    async def _update_hosts_file(self, hostname: str) -> None:
        """
        Update /etc/hosts file to reflect new hostname

        Modifies the 127.0.1.1 line:
        Before: 127.0.1.1    old-hostname
        After:  127.0.1.1    new-hostname

        Args:
            hostname: New hostname
        """
        if not self.HOSTS_FILE_PATH.exists():
            raise FileNotFoundError(f"{self.HOSTS_FILE_PATH} not found")

        backup_path: Path = self.HOSTS_FILE_PATH.with_suffix(".bak")

        # ========== Use sudo to create backup ==========
        try:
            await self._run_command("cp", str(self.HOSTS_FILE_PATH), str(backup_path))
            logger.info(f"Backed up {self.HOSTS_FILE_PATH} to {backup_path}")
        except Exception as e:
            logger.error(f"Failed to backup {self.HOSTS_FILE_PATH}: {e}")
            raise

        content: str = self.HOSTS_FILE_PATH.read_text()
        lines: list[str] = content.splitlines()

        updated_lines = []
        found = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("127.0.1.1"):
                # Update this line
                updated_lines.append(f"127.0.1.1    {hostname}")
                found = True
            else:
                updated_lines.append(line)

        # Add line if not found
        if not found:
            updated_lines.append(f"127.0.1.1    {hostname}")
            logger.warning("127.0.1.1 entry not found in /etc/hosts, adding it")

        new_content = "\n".join(updated_lines) + "\n"

        try:
            await self._write_file_with_sudo(str(self.HOSTS_FILE_PATH), new_content)
            logger.info(f"Updated /etc/hosts with hostname: {hostname}")
        except Exception as e:
            logger.error(f"Failed to update /etc/hosts, restoring backup: {e}")
            try:
                # ========== Use sudo to restore backup ==========
                await self._run_command("cp", str(backup_path), str(self.HOSTS_FILE_PATH))
                logger.info("Backup restored successfully")
            except Exception as restore_err:
                logger.critical(f"CRITICAL: Failed to restore backup: {restore_err}")
                raise RuntimeError(
                    f"Failed to restore /etc/hosts backup. "
                    f"System may be in inconsistent state. "
                    f"Manual recovery required: sudo cp {backup_path} {self.HOSTS_FILE_PATH}"
                ) from restore_err
            raise

    # ========================================
    # Reverse SSH Port Operations
    # ========================================

    def _read_reverse_port(self) -> tuple[int, str]:
        """
        Read reverse SSH port from connectserver.service

        Falls back to system_config if service file cannot be parsed.

        Returns:
            (port, source) where source is "service" or "config"
        """
        try:
            port = self._parse_service_file()
            return port, "service"
        except Exception as e:
            logger.warning(f"Failed to read port from service file: {e}")

            # Fallback to system_config
            fallback_port = self._get_fallback_port()
            logger.info(f"Using fallback port from system_config: {fallback_port}")
            return fallback_port, "config"

    def _get_fallback_port(self) -> int:
        """
        Get fallback port from system_config

        Returns:
            Port number from system_config, or 8600 if unavailable
        """
        fallback_port_num = 8600

        if self._system_config is None:
            logger.warning("[ProvisionService] system_config not available, using default port 8600")
            return fallback_port_num

        try:
            # Access via Pydantic model structure
            port = self._system_config.REMOTE_ACCESS.REVERSE_SSH.PORT
            if isinstance(port, int):
                return port
            logger.warning("[ProvisionService] REVERSE_SSH.PORT is not an integer")
            return fallback_port_num
        except Exception as e:
            logger.error(f"[ProvisionService] Failed to get fallback port: {e}")
            return fallback_port_num

    def _parse_service_file(self) -> int:
        """
        Parse reverse SSH port from connectserver.service file

        Supports formats:
        - ExecStart=... .pyc 8600 debug      (no quotes)
        - ExecStart=... .pyc "8621" debug    (with quotes)

        Returns:
            Port number

        Raises:
            FileNotFoundError: Service file not found
            ValueError: Unable to parse port
        """
        if not self.SERVICE_FILE_PATH.exists():
            raise FileNotFoundError(f"{self.SERVICE_FILE_PATH} not found")

        content = self.SERVICE_FILE_PATH.read_text()

        # Primary pattern: flexible (with or without quotes)
        # Pattern: .pyc "?8600"? debug
        match = re.search(r'\.pyc\s+"?(\d+)"?\s+debug', content)
        if match:
            port = int(match.group(1))
            if 1024 <= port <= 65535:
                return port
            raise ValueError(f"Port {port} out of valid range (1024-65535)")

        # Fallback pattern: any 4-5 digit number before "debug"
        match = re.search(r"ExecStart=.*?(\d{4,5})\s+debug", content)
        if match:
            port = int(match.group(1))
            if 1024 <= port <= 65535:
                logger.warning(f"Used fallback regex to parse port: {port}")
                return port

        raise ValueError("Unable to parse port from service file")

    async def _update_service_port(self, new_port: int) -> None:
        """
        Update port in connectserver.service file

        Preserves original format (with or without quotes).

        Args:
            new_port: New port number
        """
        if not self.SERVICE_FILE_PATH.exists():
            raise FileNotFoundError(f"{self.SERVICE_FILE_PATH} not found")

        content = self.SERVICE_FILE_PATH.read_text()

        # Replacement function that preserves quotes
        def replacement(match):
            # group(1): .pyc
            # group(2): " or empty
            # group(3): old port number
            # group(4): " or empty
            # group(5):  debug
            quote = match.group(2)
            return f"{match.group(1)}{quote}{new_port}{quote}{match.group(5)}"

        # Pattern: (\.pyc\s+)("?)(\d+)("?)(\s+debug)
        pattern = r'(\.pyc\s+)("?)(\d+)("?)(\s+debug)'
        updated_content = re.sub(pattern, replacement, content, count=1)

        if updated_content == content:
            logger.warning("Primary pattern did not match, trying fallback")
            # Fallback: replace first occurrence of 4-5 digit number before debug
            pattern = r"(ExecStart=.*?)(\d{4,5})(\s+debug)"
            updated_content = re.sub(pattern, rf"\g<1>{new_port}\g<3>", content, count=1)

        if updated_content == content:
            raise ValueError("Failed to update port in service file (no pattern matched)")

        # Write updated content
        await self._write_file_with_sudo(str(self.SERVICE_FILE_PATH), updated_content)
        logger.info(f"Updated {self.SERVICE_FILE_PATH} with port: {new_port}")

    async def _reload_and_restart_service(self):
        await self._run_command("systemctl", "daemon-reload")
        await self._run_command("systemctl", "restart", "connectserver.service")

        await asyncio.sleep(1)
        try:
            status = await self._run_command("systemctl", "is-active", "connectserver.service")
            if "active" not in status:
                logger.warning("connectserver.service may not be running correctly")
        except Exception as e:
            logger.warning(f"Failed to verify service status: {e}")

    # ========================================
    # Validation
    # ========================================

    def _validate_hostname(self, hostname: str) -> None:
        """
        Validate hostname format

        Rules:
        - Exactly 11 characters
        - Only letters (a-z, A-Z) and numbers (0-9)

        Args:
            hostname: Hostname to validate

        Raises:
            ValueError: Invalid hostname
        """
        if not hostname:
            raise ValueError("Hostname cannot be empty")

        if len(hostname) != 11:
            raise ValueError("Hostname must be exactly 11 characters")

        if not re.match(r"^[a-zA-Z0-9]+$", hostname):
            raise ValueError("Hostname can only contain letters and numbers")

    def _validate_port(self, port: int) -> None:
        """
        Validate port number

        Rules:
        - Must be between 1024 and 65535 (user port range)

        Args:
            port: Port number to validate

        Raises:
            ValueError: Invalid port
        """
        if not (1024 <= port <= 65535):
            raise ValueError("Port must be between 1024 and 65535")

    # ========================================
    # System Command Execution
    # ========================================

    async def _run_command(self, *args: str) -> str:
        """
        Execute system command (with optional sudo)

        Similar to WiFiService._run_wpa_cli pattern.

        Args:
            *args: Command and arguments

        Returns:
            Command stdout

        Raises:
            RuntimeError: Command failed or timed out
        """
        cmd = []
        if self._config.use_sudo:
            cmd.append("sudo")
        cmd += list(args)

        logger.debug(f"Executing: {' '.join(cmd)}")

        process: Process = await asyncio.create_subprocess_exec(
            cmd[0],
            *cmd[1:],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            out_b, err_b = await asyncio.wait_for(process.communicate(), timeout=self._config.timeout_sec)
        except asyncio.TimeoutError as e:
            process.kill()
            raise RuntimeError(f"Command timeout: {' '.join(cmd)}") from e

        out = out_b.decode("utf-8", errors="ignore").strip()
        err = err_b.decode("utf-8", errors="ignore").strip()

        if process.returncode != 0:
            raise RuntimeError(f"Command failed (code={process.returncode}): {' '.join(cmd)}\n" f"Error: {err}")

        return out

    async def _write_file_with_sudo(self, filepath: str, content: str) -> None:
        """
        Write file using sudo tee

        Required for writing to system files like /etc/hosts.

        Args:
            filepath: Target file path
            content: Content to write

        Raises:
            RuntimeError: Write operation failed
        """
        cmd = []
        if self._config.use_sudo:
            cmd.append("sudo")
        cmd += ["tee", filepath]

        logger.debug(f"Writing to {filepath} using tee")

        process: Process = await asyncio.create_subprocess_exec(
            cmd[0],
            *cmd[1:],
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        out_b, err_b = await process.communicate(input=content.encode("utf-8"))

        if process.returncode != 0:
            err = err_b.decode("utf-8", errors="ignore")
            raise RuntimeError(f"Failed to write {filepath}: {err}")

        logger.debug(f"Successfully wrote to {filepath}")
