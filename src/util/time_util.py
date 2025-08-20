import asyncio
import time
from datetime import datetime
from zoneinfo import ZoneInfo


async def sleep_until_next_tick(interval_sec: int | float, tz: str = "Asia/Taipei") -> datetime:
    """
    Align wall clock to the next interval tick before waking up.
    Example: interval=10, current=12:00:23 -> sleep until 12:00:30.
    Returns the wake-up time (with TZ).
    """
    tzinfo = ZoneInfo(tz)
    datetime_now: datetime = datetime.now(tzinfo)
    timestamp = int(datetime_now.timestamp())
    interval = int(interval_sec)
    next_timestamp: int = ((timestamp // interval) + 1) * interval
    sleep_sec: float = max(0.0, next_timestamp - datetime_now.timestamp())
    await asyncio.sleep(sleep_sec)
    return datetime.fromtimestamp(next_timestamp, tz=tzinfo)


async def sleep_exact_interval(interval_sec: float, start_monotonic: float | None = None) -> float:
    """
    Maintain a fixed rhythm using monotonic clock to avoid drift caused by system time adjustments.
    Returns the next monotonic baseline time (can be passed directly into the next call).
    """
    if start_monotonic is None:
        start_monotonic = time.monotonic()
    target: float = start_monotonic + interval_sec
    delay: float = max(0.0, target - time.monotonic())
    await asyncio.sleep(delay)
    return target
