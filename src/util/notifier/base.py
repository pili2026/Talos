from abc import ABC, abstractmethod

from schema.alert_schema import AlertMessageModel


class BaseNotifier(ABC):
    @abstractmethod
    async def send(self, alert: AlertMessageModel): ...
