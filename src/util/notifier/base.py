from abc import ABC, abstractmethod

from model.alert_model import AlertMessageModel


class BaseNotifier(ABC):
    @abstractmethod
    async def send(self, alert: AlertMessageModel): ...
