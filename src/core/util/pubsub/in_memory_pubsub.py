import asyncio
from collections import defaultdict
from typing import Any, AsyncGenerator, DefaultDict

from core.util.pubsub.base import PubSub


class InMemoryPubSub(PubSub):
    def __init__(self):
        self._topic_subscribers: DefaultDict[str, list[asyncio.Queue]] = defaultdict(list)

    async def publish(self, topic: str, data: Any):
        for queue in self._topic_subscribers[topic]:
            await queue.put(data)

    async def subscribe(self, topic: str) -> AsyncGenerator[Any, None]:
        queue = asyncio.Queue()
        self._topic_subscribers[topic].append(queue)

        try:
            while True:
                data = await queue.get()
                yield data
        finally:
            self._topic_subscribers[topic].remove(queue)

    async def close(self):
        self._topic_subscribers.clear()
