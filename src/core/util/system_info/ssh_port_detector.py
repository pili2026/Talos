"""
SSH Port Detector

Responsibility: Automatically detect the port on which the SSH service is listening
"""

import asyncio
import logging
import re
from pathlib import Path

logger = logging.getLogger("SSHPortDetector")


class SSHPortDetector:
    """
    SSH Port Detector

    Detection strategy (priority order):
    1. ConnectServer systemd service
    2. Running sshd process (ss/netstat)
    3. /etc/ssh/sshd_config configuration file
    4. Default value: 22
    """

    def __init__(self):
        self._port_cache: int | None = None

    async def detect(self) -> int:
        """
        Detect SSH port

        Returns:
            int: SSH port number
        """
        # Return cached port if available
        if self._port_cache is not None:
            logger.debug(f"Using cached SSH port: {self._port_cache}")
            return self._port_cache

        # Try detection methods in priority order
        detectors = [
            ("ConnectServer service", self._from_connectserver),
            ("running process", self._from_process),
            ("sshd_config", self._from_config),
        ]

        for name, detector in detectors:
            port = await detector()
            if port:
                self._port_cache = port
                logger.info(f"Detected SSH port from {name}: {port}")
                return port

        # All methods failed, use default value
        self._port_cache = 22
        logger.info("Using default SSH port: 22")
        return 22

    def clear_cache(self):
        """Clear cache (used for re-detection)"""
        self._port_cache = None
        logger.debug("SSH port cache cleared")

    async def _from_connectserver(self) -> int | None:
        """
        Read from ConnectServer systemd service config

        File: /etc/systemd/system/connectserver.service
        Example line: ExecStart=/usr/bin/python3 /home/pi/ConnectServer_py3.cpython-39.pyc 8426 debug
        Extracted value: 8426

        Returns:
            int | None: SSH port number, None if failed
        """
        service_path = Path("/etc/systemd/system/connectserver.service")

        try:
            if not service_path.exists():
                logger.debug("connectserver.service not found")
                return None

            content = service_path.read_text()

            for line in content.split("\n"):
                line = line.strip()

                # Skip comments
                if line.startswith("#"):
                    continue

                # Look for ExecStart line
                if line.startswith("ExecStart="):
                    # Remove prefix
                    exec_line = line[len("ExecStart=") :].strip()
                    parts = exec_line.split()

                    # Look for ConnectServer-related file
                    for i, part in enumerate(parts):
                        if "ConnectServer" in part and part.endswith((".pyc", ".py")):
                            # Port should be the next argument
                            if i + 1 < len(parts):
                                try:
                                    port = int(parts[i + 1])
                                    # Validate port range
                                    if 1 <= port <= 65535:
                                        logger.debug(f"Found SSH port in ConnectServer: {port}")
                                        return port
                                    else:
                                        logger.warning(f"Invalid port in ConnectServer: {port}")
                                except ValueError:
                                    logger.debug(f"Non-numeric port value: {parts[i + 1]}")
                                    continue
        except Exception as e:
            logger.debug(f"Failed to read ConnectServer service: {e}")

        return None

    async def _from_process(self) -> int | None:
        """
        Detect from running sshd process

        Uses `ss` or `netstat` command

        Returns:
            int | None: SSH port number, None if failed
        """
        # Prefer ss (more modern)
        port = await self._run_command("ss", "-tlnp")
        if port:
            logger.debug(f"Found SSH port via ss: {port}")
            return port

        # Fallback: netstat
        port = await self._run_command("netstat", "-tlnp")
        if port:
            logger.debug(f"Found SSH port via netstat: {port}")
            return port

        return None

    async def _run_command(self, cmd: str, *args: str) -> int | None:
        """
        Execute command and parse SSH port

        Args:
            cmd: Command name (ss or netstat)
            *args: Command arguments

        Returns:
            int | None: SSH port number, None if failed
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                cmd, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.debug(f"{cmd} command failed with code {proc.returncode}")
                return None

            output = stdout.decode()

            # Look for line containing sshd
            for line in output.split("\n"):
                if "sshd" in line.lower():
                    # Extract port number: 0.0.0.0:2222 or [::]:2222 or *:2222
                    match = re.search(r"(?:0\.0\.0\.0|::|\*):(\d+)", line)
                    if match:
                        port = int(match.group(1))
                        return port

        except FileNotFoundError:
            logger.debug(f"{cmd} command not found")
        except Exception as e:
            logger.debug(f"{cmd} command failed: {e}")

        return None

    async def _from_config(self) -> int | None:
        """
        Read from /etc/ssh/sshd_config

        Look for 'Port' config line

        Returns:
            int | None: SSH port number, None if failed
        """
        config_path = Path("/etc/ssh/sshd_config")

        try:
            if not config_path.exists():
                logger.debug("sshd_config not found")
                return None

            content = config_path.read_text()

            for line in content.split("\n"):
                line = line.strip()

                # Skip comments
                if line.startswith("#"):
                    continue

                # Look for Port config
                match = re.match(r"^Port\s+(\d+)", line, re.IGNORECASE)
                if match:
                    port = int(match.group(1))
                    logger.debug(f"Found SSH port in sshd_config: {port}")
                    return port

        except Exception as e:
            logger.debug(f"Failed to read sshd_config: {e}")

        return None

    def __repr__(self) -> str:
        return f"SSHPortDetector(cached_port={self._port_cache})"
