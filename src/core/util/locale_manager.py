import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class LocaleConfig:
    """Locale configuration for alert messages"""

    message_format: str
    field_labels: dict[str, str]
    operators: dict[str, str]
    level_names: dict[str, str]
    level_emojis: dict[str, str]


class LocaleNotFoundError(Exception):
    """Raised when locale file is not found"""

    pass


class LocaleManager:
    """Manage locale configurations for alert messages"""

    _instance: Optional["LocaleManager"] = None

    def __new__(cls, *args, **kwargs):
        """Singleton pattern"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    # TODO: Need to refactor to support dynamic locale directory change
    def __init__(self, locale_dir: Path | str = "res/locales/alert"):
        if hasattr(self, "_initialized"):
            return

        self.locale_dir = Path(locale_dir)
        self._locales: dict[str, LocaleConfig] = {}
        self._default_locale = "zh_TW"
        self._load_locales()
        self._initialized = True

    def get_locale(self, locale_code: str | None = None) -> LocaleConfig:
        """
        Get locale configuration

        Args:
            locale_code: Locale code (e.g., 'zh_TW', 'en_US').
                        If None, returns default locale.

        Returns:
            LocaleConfig for the requested locale

        Raises:
            LocaleNotFoundError: If requested locale is not available
        """
        if locale_code is None:
            locale_code = self._default_locale

        if locale_code not in self._locales:
            available = self.get_available_locales()
            raise LocaleNotFoundError(
                f"Locale '{locale_code}' not found. " f"Available locales: {', '.join(available)}"
            )

        return self._locales[locale_code]

    def set_default_locale(self, locale_code: str):
        """
        Set default locale

        Args:
            locale_code: Locale code to set as default

        Raises:
            LocaleNotFoundError: If locale is not available
        """
        if locale_code not in self._locales:
            available = self.get_available_locales()
            raise LocaleNotFoundError(
                f"Cannot set default locale to '{locale_code}'. " f"Available locales: {', '.join(available)}"
            )

        self._default_locale = locale_code
        logger.info(f"Default locale set to: {locale_code}")

    def get_available_locales(self) -> list[str]:
        """Get list of available locales"""
        return list(self._locales.keys())

    def get_default_locale(self) -> str:
        """Get current default locale code"""
        return self._default_locale

    def _load_locales(self):
        """Load all locale files from directory"""
        if not self.locale_dir.exists():
            raise LocaleNotFoundError(
                f"Locale directory not found: {self.locale_dir}\n"
                f"Please create the directory and add locale files (e.g., zh_TW.yaml, en_US.yaml)"
            )

        locale_files = list(self.locale_dir.glob("*.yaml"))

        if not locale_files:
            raise LocaleNotFoundError(
                f"No locale files found in {self.locale_dir}\n"
                f"Please add at least one locale file (e.g., zh_TW.yaml)"
            )

        for locale_file in locale_files:
            locale_code = locale_file.stem
            try:
                self._load_locale_file(locale_file, locale_code)
                logger.info(f"Loaded locale: {locale_code} from {locale_file}")
            except Exception as e:
                logger.error(f"Failed to load locale {locale_code}: {e}")
                raise

        # Verify default locale exists
        if self._default_locale not in self._locales:
            available = list(self._locales.keys())
            if available:
                self._default_locale = available[0]
                logger.warning(f"Default locale 'zh_TW' not found, using '{self._default_locale}' instead")
            else:
                raise LocaleNotFoundError("No valid locale configurations loaded")

    def _load_locale_file(self, locale_file: Path, locale_code: str):
        """Load a single locale file"""
        with open(locale_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data or "alert" not in data:
            raise ValueError(f"Invalid locale file {locale_file}: missing 'alert' section")

        alert_config = data["alert"]

        # Validate required fields
        required_fields = ["message_format", "field_labels", "operators", "level_names", "level_emojis"]

        missing_fields = [field for field in required_fields if field not in alert_config]

        if missing_fields:
            raise ValueError(f"Invalid locale file {locale_file}: missing fields {missing_fields}")

        self._locales[locale_code] = LocaleConfig(
            message_format=alert_config["message_format"],
            field_labels=alert_config["field_labels"],
            operators=alert_config["operators"],
            level_names=alert_config["level_names"],
            level_emojis=alert_config["level_emojis"],
        )
