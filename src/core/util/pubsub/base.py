from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator

from core.util.pubsub.pubsub_topic import PubSubTopic


class PubSub(ABC):
    @abstractmethod
    async def publish(self, topic: PubSubTopic, data: Any) -> None:
        raise NotImplementedError

    @abstractmethod
    async def subscribe(self, topic: PubSubTopic) -> AsyncGenerator[Any, None]:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError
