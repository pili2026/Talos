"""Basic authentication utilities for admin operations."""

import logging
import os

from fastapi import Header, HTTPException

from util.config_manager import ConfigManager

logger = logging.getLogger(__name__)


class AdminAuth:
    """
    Simple admin authentication using API key.

    Security notes:
    - Use environment variable or secure config for production
    - Deploy behind HTTPS in production
    - Rotate keys periodically
    """

    def __init__(self):
        # Priority: ENV_VAR > config file > default (insecure)
        self.admin_key: str = self._load_admin_key()

        if self.admin_key == "change-me-in-production":
            logger.warning("Using default admin key! " "Set TALOS_ADMIN_KEY environment variable in production.")

    def _load_admin_key(self) -> str:
        """Load admin key from environment or config."""

        # 1. Try environment variable (highest priority)
        env_key: str | None = os.getenv("TALOS_ADMIN_KEY")
        if env_key:
            logger.info("[Auth] Admin key loaded from environment variable")
            return env_key

        # 2. Try config file
        try:
            auth_config: dict = ConfigManager.load_yaml_file("config/api_auth.yaml")
            config_key: str = auth_config.get("admin_key")

            if config_key:
                logger.info("[Auth] Admin key loaded from config file")
                return config_key
        except Exception as e:
            logger.debug(f"[Auth] Could not load from config: {e}")

        # 3. Fallback to default (insecure - for development only)
        logger.warning("[Auth] Using default admin key (development only)")
        return "change-me-in-production"

    def verify_key(self, provided_key: str) -> bool:
        """Verify if provided key matches admin key."""
        return provided_key == self.admin_key


# Singleton instance
_admin_auth = AdminAuth()


def verify_admin_key(x_admin_key: str = Header(..., description="Admin API key")) -> None:
    """
    FastAPI dependency to verify admin key.

    Usage:
        @router.delete("/admin-operation")
        async def admin_op(
            _: None = Depends(verify_admin_key)
        ):
            ...

    Raises:
        HTTPException: 403 if key is invalid or missing
    """
    if not _admin_auth.verify_key(x_admin_key):
        logger.warning(f"[Auth] Invalid admin key attempt: {x_admin_key[:8]}...")
        raise HTTPException(
            status_code=403,
            detail="Invalid admin key. Set X-Admin-Key header with valid key.",
        )

    logger.info("[Auth] Admin key verified successfully")
