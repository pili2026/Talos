import asyncio
import logging
from typing import Awaitable, Callable

from schema.system_config_schema import SubscribersConfig

logger = logging.getLogger("SubscriberRegistry")

Runner = Callable[[], Awaitable[None]]


class SubscriberRegistry:
    def __init__(self, enabled_sub: SubscribersConfig) -> None:
        """
        :param enabled_sub: Switch setting from YAML/ENV
        """
        self._enabled_sub = enabled_sub
        self.subs: dict[str, Runner] = {}
        self.tasks: dict[str, asyncio.Task] = {}

    def register(self, name: str, runner: Runner) -> None:
        if name in self.subs:
            logger.warning(f"[SUB] Subscriber '{name}' already registered, skip")
            return
        self.subs[name] = runner

    async def start_enabled_sub(self) -> None:
        for name, runner in self.subs.items():
            if not self._enabled_sub[name]:
                logger.info(f"[SUB] {name} is disabled, skipping")
                continue

            if name in self.tasks and not self.tasks[name].done():
                logger.warning(f"[SUB] {name} is already running, skipping")
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
        status_dict = {}
        for name in self.subs:
            t = self.tasks.get(name)
            if t is None:
                status_dict[name] = "not started"
            elif t.cancelled():
                status_dict[name] = "cancelled"
            elif t.done():
                status_dict[name] = "done" if t.exception() is None else f"error: {t.exception()}"
            else:
                status_dict[name] = "running"
        return status_dict
