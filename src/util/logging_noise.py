import asyncio
import logging
import time


class RateLimitFilter(logging.Filter):
    def __init__(self, period_sec: float = 2.0):
        super().__init__()
        self.period = period_sec
        self._last: dict[tuple, float] = {}

    def filter(self, record: logging.LogRecord) -> bool:
        key = (record.name, record.levelno, record.getMessage())
        now = time.monotonic()
        last = self._last.get(key, 0.0)
        if now - last < self.period:
            return False
        self._last[key] = now
        return True


def quiet_pymodbus_logs(level=logging.WARNING, rate_limit_sec: float = 2.0):
    pymodbus_log = logging.getLogger("pymodbus.logging")
    pymodbus_log.setLevel(level)
    pymodbus_log.addFilter(RateLimitFilter(rate_limit_sec))

    async_log = logging.getLogger("asyncio")
    async_log.setLevel(logging.ERROR)


def install_asyncio_noise_suppressor():
    loop = asyncio.get_running_loop()
    default_handler = loop.get_exception_handler()

    def handler(loop, ctx):
        exc = ctx.get("exception")
        msg = ctx.get("message", "")

        noisy = (
            (exc and exc.__class__.__name__ == "ModbusIOException")
            or ("SerialTransport.intern_read_ready" in msg)
            or ("Unable to decode frame" in msg)
            or ("Unable to decode request" in msg)
            or ("Unknown response" in msg)
        )
        if noisy:
            logging.getLogger("pymodbus.rtunoise").warning("RTU noise / bad frame suppressed: %s", exc or msg)
            return

        if default_handler:
            default_handler(loop, ctx)
        else:
            loop.default_exception_handler(ctx)

    loop.set_exception_handler(handler)
