import logging
import os

logger = logging.getLogger("DashboardHelper")


class DashboardHelper:
    """Helper for generating dashboard URLs"""

    def __init__(self):
        self.base_url = os.getenv("TALOS_DASHBOARD_BASE_URL")
        if not self.base_url:
            logger.warning("TALOS_DASHBOARD_BASE_URL not set, dashboard links will be disabled")

    def get_device_url(self) -> str | None:
        """Generate device dashboard URL"""
        if not self.base_url:
            return None

        return self.base_url

    def get_alert_url(self) -> str | None:
        """Generate alert dashboard URL"""
        if not self.base_url:
            return None

        return self.base_url
