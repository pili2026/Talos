from abc import ABC, abstractmethod
from typing import AsyncGenerator


class PubSub(ABC):
    @abstractmethod
    async def publish(self, topic: str, data: any):
        pass

    @abstractmethod
    def subscribe(self, topic: str) -> AsyncGenerator[any, None]:
        pass

    @abstractmethod
    async def close(self):
        pass
