import asyncio
import functools
import inspect
import logging
from typing import Any, Callable


def async_retry(
    max_retries: int = None,  # Maximum number of retries, None for unlimited
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    logger: logging.Logger = None,
    key_name: str = "device_id",  # Key to identify the device in kwargs
):
    def decorator(func: Callable):
        signature = inspect.signature(func)

        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            retry_count = 0

            bound_args = signature.bind(*args, **kwargs)
            bound_args.apply_defaults()
            device_id = bound_args.arguments.get(key_name, None)

            while True:
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    retry_count += 1
                    wait_sec = min(base_delay * retry_count, max_delay)

                    log_prefix = f"{func.__class__.__name__}"
                    if device_id:
                        log_prefix += f" for device {device_id}"

                    if logger:
                        logger.warning(f"[Retry #{retry_count}] {log_prefix} failed: {e}. Retrying in {wait_sec}s")

                    if max_retries is not None and retry_count >= max_retries:
                        if logger:
                            logger.error(f"{log_prefix} failed after {retry_count} retries. Giving up.")
                        raise e

                    await asyncio.sleep(wait_sec)

        return wrapper

    return decorator
