import asyncio
from collections import defaultdict
from typing import Any, AsyncGenerator, DefaultDict

from util.pubsub.base import PubSub


class InMemoryPubSub(PubSub):
    def __init__(self):
        self._topic_events: DefaultDict[str, list[asyncio.Event]] = defaultdict(list)
        self._topic_data: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def publish(self, topic: str, data: Any):
        async with self._lock:
            self._topic_data[topic] = data
            for event in self._topic_events[topic]:
                event.set()

    async def subscribe(self, topic: str) -> AsyncGenerator[Any, None]:
        event = asyncio.Event()
        self._topic_events[topic].append(event)

        try:
            while True:
                await event.wait()
                yield self._topic_data.get(topic)
                event.clear()
        finally:
            self._topic_events[topic].remove(event)

    async def close(self):
        self._topic_events.clear()
        self._topic_data.clear()
