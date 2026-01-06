import asyncio
import logging
import os
import socket

logger = logging.getLogger("SystemdWatchdog")


class SystemdWatchdog:
    """
    systemd sd_notify helper:
    - READY/STATUS: requires NOTIFY_SOCKET
    - WATCHDOG=1: requires WATCHDOG_USEC (usually set when WatchdogSec=... in unit)
    """

    def __init__(self, interval_sec: float | None = None):
        self._notify_socket = os.getenv("NOTIFY_SOCKET") or ""
        self._watchdog_usec = os.getenv("WATCHDOG_USEC")  # may be None

        self._notify_enabled = bool(self._notify_socket)
        self._watchdog_enabled = bool(self._notify_socket and self._watchdog_usec)

        self._interval_sec: float | None = interval_sec
        self._stopping = asyncio.Event()

        if self._watchdog_enabled:
            try:
                wd_usec = int(self._watchdog_usec)  # type: ignore[arg-type]
                default_interval = (wd_usec / 1_000_000.0) / 2.0  # ping at half watchdog interval
                self._interval_sec = float(interval_sec) if interval_sec else max(1.0, default_interval)
                logger.info(f"[systemd] watchdog enabled: interval={self._interval_sec:.3f}s")
            except Exception as e:
                self._watchdog_enabled = False
                logger.warning(f"[systemd] watchdog disabled (WATCHDOG_USEC invalid): {e}")
        else:
            if self._notify_enabled:
                logger.info("[systemd] notify enabled (READY/STATUS available); watchdog disabled")
            else:
                logger.info("[systemd] notify disabled (NOTIFY_SOCKET not set)")

    def stop(self) -> None:
        self._stopping.set()

    def notify_ready(self, status: str | None = None) -> None:
        if not self._notify_enabled:
            return
        msg = "READY=1"
        if status:
            msg += f"\nSTATUS={status}"
        self._notify(msg)

    def notify_status(self, status: str) -> None:
        if not self._notify_enabled:
            return
        self._notify(f"STATUS={status}")

    def notify_watchdog(self) -> None:
        if not self._watchdog_enabled:
            return
        self._notify("WATCHDOG=1")

    async def run(self) -> None:
        """
        Periodically send WATCHDOG=1.
        Note: Does NOT send READY=1 automatically.
        """
        if not self._watchdog_enabled:
            return

        assert self._interval_sec is not None
        try:
            while not self._stopping.is_set():
                self.notify_watchdog()
                await asyncio.sleep(self._interval_sec)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"[systemd] watchdog loop failed: {e}")

    def _notify(self, msg: str) -> None:
        if not self._notify_enabled:
            return

        addr = self._notify_socket
        if not addr:
            return

        # abstract namespace socket: "@name" -> "\0name"
        if addr.startswith("@"):
            addr = "\0" + addr[1:]

        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            try:
                # connect+sendall is generally more reliable than sendto here
                sock.connect(addr)
                sock.sendall(msg.encode("utf-8"))
            finally:
                sock.close()
        except Exception as e:
            logger.warning(f"[systemd] notify failed: {e}")
