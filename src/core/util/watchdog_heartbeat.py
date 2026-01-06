import asyncio
import faulthandler
import json
import logging
import os
import signal
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from core.util.time_util import TIMEZONE_INFO

logger = logging.getLogger("WatchdogHeartbeat")


@dataclass(frozen=True)
class WatchdogHeartbeatConfig:
    heartbeat_path: str = "logs/state/heartbeat.txt"
    interval_sec: float = 5.0

    # event loop lag detection
    lag_check_sec: float = 1.0
    lag_warn_sec: float = 1.5  # Record warning when over this time
    lag_critical_sec: float = 5.0  # Record error when over this time

    # write mode
    json_mode: bool = True  # True: Write to JSON; False: Write time string
    atomic_write: bool = True


class WatchdogHeartbeat:
    """
    - Writes a heartbeat file periodically (for external watchdog).
    - Measures event loop lag (drift) and logs when abnormal.
    - Optionally embeds lag info into the heartbeat file (JSON mode).
    """

    def __init__(self, cfg: WatchdogHeartbeatConfig):
        self.cfg = cfg
        self._stopping = asyncio.Event()

        # latest measured stats
        self._last_lag_sec: float = 0.0
        self._max_lag_sec: float = 0.0
        self._last_tick_monotonic: float | None = None

    def stop(self) -> None:
        self._stopping.set()

    # -------------------------
    # Public entrypoints
    # -------------------------

    async def run(self) -> None:
        """
        Run both:
        - lag monitor loop
        - heartbeat writer loop
        """
        hb_path = Path(self.cfg.heartbeat_path)
        hb_path.parent.mkdir(parents=True, exist_ok=True)

        lag_task = asyncio.create_task(self._lag_monitor_loop())
        hb_task = asyncio.create_task(self._heartbeat_loop())

        try:
            await self._stopping.wait()
        finally:
            for t in (lag_task, hb_task):
                t.cancel()
            await asyncio.gather(lag_task, hb_task, return_exceptions=True)

    # -------------------------
    # Internal loops
    # -------------------------

    async def _lag_monitor_loop(self) -> None:
        """
        Measure event loop drift:
        - expected: sleep(lag_check_sec)
        - actual: monotonic delta
        - lag = actual - expected
        """
        expected = float(self.cfg.lag_check_sec)
        self._last_tick_monotonic = time.monotonic()

        while not self._stopping.is_set():
            await asyncio.sleep(expected)

            now = time.monotonic()
            prev = self._last_tick_monotonic or now
            self._last_tick_monotonic = now

            actual = now - prev
            lag = max(0.0, actual - expected)

            self._last_lag_sec = lag
            if lag > self._max_lag_sec:
                self._max_lag_sec = lag

            # log on thresholds
            if lag >= self.cfg.lag_critical_sec:
                logger.error(f"[LoopLag] critical lag={lag:.3f}s (expected={expected:.3f}s, actual={actual:.3f}s)")
            elif lag >= self.cfg.lag_warn_sec:
                logger.warning(f"[LoopLag] warning lag={lag:.3f}s (expected={expected:.3f}s, actual={actual:.3f}s)")

    async def _heartbeat_loop(self) -> None:
        """
        Periodically write heartbeat file.
        In JSON mode we also write loop lag stats for observability.
        """
        interval = float(self.cfg.interval_sec)
        hb_path = Path(self.cfg.heartbeat_path)

        while not self._stopping.is_set():
            payload: str
            now_dt = datetime.now(TIMEZONE_INFO)

            if self.cfg.json_mode:
                obj: dict[str, Any] = {
                    "ts": now_dt.isoformat(),
                    "pid": os.getpid(),
                    "loop_lag_sec": round(self._last_lag_sec, 6),
                    "loop_lag_max_sec": round(self._max_lag_sec, 6),
                }
                payload = json.dumps(obj, ensure_ascii=False)
            else:
                payload = now_dt.isoformat()

            try:
                if self.cfg.atomic_write:
                    tmp = hb_path.with_suffix(hb_path.suffix + ".tmp")
                    tmp.write_text(payload, encoding="utf-8")
                    os.replace(tmp, hb_path)
                else:
                    hb_path.write_text(payload, encoding="utf-8")
            except Exception as e:
                logger.warning(f"[Heartbeat] write failed: path={hb_path} err={e}")

            await asyncio.sleep(interval)


def install_sigusr1_stackdump() -> None:
    """
    Enable Python faulthandler and register SIGUSR1 to dump all threads' stack traces.

    External watchdog can do:
      kill -USR1 <MainPID>
    and you'll see stack traces in journald/stderr.
    """
    try:
        faulthandler.enable(all_threads=True)
        faulthandler.register(signal.SIGUSR1, all_threads=True, chain=False)
        logger.info("[Faulthandler] SIGUSR1 stack dump enabled")
    except Exception as e:
        logger.warning(f"[Faulthandler] enable failed: {e}")
