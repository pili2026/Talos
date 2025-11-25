import asyncio
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class AsyncRecurringJob(ABC):
    """
    Base class for recurring asynchronous background jobs.

    Subclasses must implement `run_once()`, which will be executed
    every interval. Task lifecycle, loop handling, exception management,
    and cooperative cancellation are all provided by this base class.
    """

    def __init__(self, interval_seconds: float):
        """
        Args:
            interval_seconds: Time between each execution of `run_once()`.
        """
        self._interval = float(interval_seconds)
        self._task: asyncio.Task | None = None
        self._stopping: bool = False

    # ----------------------------------------------------------------------
    # Required implementation in subclasses
    # ----------------------------------------------------------------------
    @abstractmethod
    async def run_once(self) -> None:
        """
        The operation that should be executed once per loop.
        Subclasses must implement this method.
        """
        ...

    # ----------------------------------------------------------------------
    # Internal background loop
    # ----------------------------------------------------------------------
    async def _loop(self) -> None:
        """Internal loop executed inside the background task."""
        logger.info(f"[{self.__class__.__name__}] loop started (interval={self._interval}s)")

        while not self._stopping:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                logger.info(f"[{self.__class__.__name__}] task cancelled")
                break
            except Exception as e:
                logger.exception(f"[{self.__class__.__name__}] exception in run_once: {e}")

            # Sleep between iterations
            if self._interval > 0 and not self._stopping:
                try:
                    await asyncio.sleep(self._interval)
                except asyncio.CancelledError:
                    break

        logger.info(f"[{self.__class__.__name__}] loop stopped")

    # ----------------------------------------------------------------------
    # Public API: start & stop
    # ----------------------------------------------------------------------
    def start(self) -> asyncio.Task:
        """
        Start the recurring job in the background.

        Returns:
            asyncio.Task: The background task handle.
        """
        if self._task and not self._task.done():
            logger.warning(f"[{self.__class__.__name__}] already running")
            return self._task

        self._stopping = False
        self._task = asyncio.create_task(self._loop())
        return self._task

    async def stop(self) -> None:
        """
        Stop the background job and wait for the task to finish.
        Safe to call even if the job is not running.
        """
        self._stopping = True

        if not self._task:
            return

        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
