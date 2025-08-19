import asyncio
import logging
from typing import Awaitable, Callable

logger = logging.getLogger("SubscriberRegistry")

Runner = Callable[[], Awaitable[None]]


class SubscriberRegistry:
    def __init__(self, enabled: dict[str, bool]) -> None:
        """
        :param enabled: Switch setting from YAML/ENV
        """
        self.enabled = dict(enabled)
        self.subs: dict[str, Runner] = {}
        self.tasks: dict[str, asyncio.Task] = {}

    def register(self, name: str, runner: Runner) -> None:
        if name in self.subs:
            raise ValueError(f"Subscriber '{name}' already registered")
        self.subs[name] = runner

    async def start_enabled(self) -> None:
        for name, runner in self.subs.items():
            if not self.enabled.get(name, True):
                logger.info(f" {name} disabled")
                continue
            if name in self.tasks and not self.tasks[name].done():
                continue
            logger.info(f"[Starting {name}")
            self.tasks[name] = asyncio.create_task(runner(), name=f"sub:{name}")

    async def stop(self, name: str) -> None:
        task = self.tasks.get(name)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.info(f"{name} cancelled")
        self.tasks.pop(name, None)

    async def stop_all(self) -> None:
        logger.info("Stopping all subscribers ...")
        await asyncio.gather(*(self.stop(n) for n in list(self.tasks.keys())))
        logger.info("All subscribers stopped")

    def status(self) -> dict[str, str]:
        st = {}
        for name in self.subs:
            t = self.tasks.get(name)
            if t is None:
                st[name] = "not started"
            elif t.cancelled():
                st[name] = "cancelled"
            elif t.done():
                st[name] = "done" if t.exception() is None else f"error: {t.exception()}"
            else:
                st[name] = "running"
        return st
