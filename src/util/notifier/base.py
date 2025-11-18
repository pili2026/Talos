from abc import ABC, abstractmethod

from schema.alert_schema import AlertMessageModel


class BaseNotifier(ABC):
    """
    Base class for all notifiers.
    Priority is now passed from config, not hardcoded.
    """

    def __init__(self, priority: int, enabled: bool = True):
        self.priority = priority
        self.enabled = enabled

    @abstractmethod
    async def send(self, alert: AlertMessageModel):
        """
        Send notification.

        Returns:
            bool: True if successful, False if failed
        """
        ...

    @property
    def notifier_type(self) -> str:
        """Return notifier type name for logging"""
        return self.__class__.__name__
