import asyncio
import logging
import time


class RateLimitFilter(logging.Filter):
    """
    Rate limit filter to prevent log spam.
    Only allows the same log message once per period.
    """

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


def install_asyncio_noise_suppressor():
    """
    Suppress asyncio noise from Modbus communication errors.

    Catches asyncio exceptions related to Modbus/RS-485 noise and logs them
    as suppressed warnings instead of letting them propagate as unhandled exceptions.

    This is complementary to logging level configuration:
    - This function: Handles exceptions at the asyncio event loop level
    - setup_logging(): Configures log levels to suppress the resulting log messages
    """
    loop = asyncio.get_running_loop()
    default_handler = loop.get_exception_handler()

    def handler(loop, ctx):
        exc = ctx.get("exception")
        msg = ctx.get("message", "")

        # Detect noisy Modbus/RS-485 errors
        noisy = (
            (exc and exc.__class__.__name__ == "ModbusIOException")
            or ("SerialTransport.intern_read_ready" in msg)
            or ("Unable to decode frame" in msg)
            or ("Unable to decode request" in msg)
            or ("Unknown response" in msg)
        )

        if noisy:
            # Log as suppressed warning (will be filtered by CRITICAL level in setup_logging)
            logging.getLogger("pymodbus.rtunoise").warning("RTU noise / bad frame suppressed: %s", exc or msg)
            return

        # Pass through other exceptions to default handler
        if default_handler:
            default_handler(loop, ctx)
        else:
            loop.default_exception_handler(ctx)

    loop.set_exception_handler(handler)
