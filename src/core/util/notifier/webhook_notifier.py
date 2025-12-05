import logging
from abc import abstractmethod

import httpx

from core.schema.alert_schema import AlertMessageModel
from core.util.notifier.base import BaseNotifier


class WebhookNotifier(BaseNotifier):
    """
    Abstract base class for webhook-based notifiers.
    Handles common HTTP logic, subclasses implement platform-specific payload building.
    """

    def __init__(
        self,
        url: str,
        priority: int = 2,
        enabled: bool = True,
        timeout_sec: float = 5.0,
        platform: str = "generic",
    ):
        super().__init__(priority=priority, enabled=enabled)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.url = url
        self.timeout_sec = timeout_sec
        self.platform = platform

    async def send(self, alert: AlertMessageModel) -> bool:
        if not self.enabled:
            self.logger.debug(f"[{self.platform.upper()}] Notifier is disabled, skipping")
            return False

        if not self.url:
            self.logger.warning(f"[{self.platform.upper()}] URL not configured, skipping")
            return False

        try:
            payload = self._build_payload(alert)
            headers = self._get_headers()

            async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
                response = await client.post(self.url, json=payload, headers=headers)

                if self._is_success(response):
                    self.logger.info(f"[{self.platform.upper()}] Successfully sent: {alert.alert_code}")
                    return True
                else:
                    self.logger.warning(
                        f"[{self.platform.upper()}] Failed with status {response.status_code}: {response.text[:200]}"
                    )
                    return False

        except httpx.TimeoutException:
            self.logger.error(f"[{self.platform.upper()}] Timeout after {self.timeout_sec}s")
            return False
        except Exception as e:
            self.logger.error(f"[{self.platform.upper()}] Failed to send: {e}")
            return False

    @abstractmethod
    def _build_payload(self, alert: AlertMessageModel) -> dict:
        """
        Build platform-specific payload.
        Must be implemented by subclasses.
        """
        ...

    def _get_headers(self) -> dict:
        """
        Get HTTP headers. Can be overridden by subclasses.
        """
        return {"Content-Type": "application/json"}

    def _is_success(self, response: httpx.Response) -> bool:
        """
        Check if response indicates success. Can be overridden by subclasses.
        """
        return response.status_code == 200
