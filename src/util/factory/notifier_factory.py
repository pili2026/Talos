import logging

from schema.notifier_schema import NotificationConfigSchema, NotifierConfigSchema
from util.config_manager import ConfigManager
from util.notifier.base import BaseNotifier
from util.notifier.email_notifier import EmailNotifier
from util.notifier.sms_notifier import SmsNotifier
from util.notifier.telegram_notifier import TelegramNotifier

logger = logging.getLogger("NotifierFactory")


def build_notifiers_and_routing(config_path: str) -> tuple[list[BaseNotifier], NotificationConfigSchema]:
    """
    Build notifiers and routing rules from config with Pydantic validation.

    Returns:
        tuple: (notifier_list, validated_config_schema)
    """
    # Load raw config
    raw_config: dict = ConfigManager.load_yaml_file(config_path)

    # Parse environment variables in confi
    raw_config = _parse_env_vars_recursive(raw_config)

    # Validate with Pydantic (will raise ValidationError if invalid)
    try:
        config = NotificationConfigSchema(**raw_config)
        logger.info("Notification config validated successfully")
    except Exception as e:
        logger.error(f"Invalid notification config: {e}")
        raise

    # Build notifiers from validated schema
    notifiers = _build_notifiers(config.notifiers)

    logger.info(f"Notification system initialized with {len(notifiers)} notifiers")

    return notifiers, config


def _parse_env_vars_recursive(obj):
    """Recursively parse environment variables in config"""
    if isinstance(obj, dict):
        return {k: _parse_env_vars_recursive(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_parse_env_vars_recursive(item) for item in obj]
    elif isinstance(obj, str):
        return ConfigManager.parse_env_var_with_default(obj)
    else:
        return obj


def _build_notifiers(config: NotifierConfigSchema) -> list[BaseNotifier]:
    """Build notifier instances from validated schema"""
    notifiers: list[BaseNotifier] = []

    # SMS
    if config.sms and config.sms.enabled:
        notifiers.append(
            SmsNotifier(
                phone_numbers=config.sms.phone_numbers,
                priority=config.sms.priority,
                enabled=config.sms.enabled,
            )
        )
        logger.info(f"[SMS] Initialized with {len(config.sms.phone_numbers)} phone numbers")

    # Telegram
    if config.telegram and config.telegram.enabled:
        if not config.telegram.bot_token or not config.telegram.chat_id:
            logger.warning("[TELEGRAM] Enabled but bot_token/chat_id is empty, skipping")
        else:
            notifiers.append(
                TelegramNotifier(
                    bot_token=config.telegram.bot_token,
                    chat_id=config.telegram.chat_id,
                    priority=config.telegram.priority,
                    enabled=config.telegram.enabled,
                    timeout_sec=config.telegram.timeout_sec,
                    parse_mode=config.telegram.parse_mode,
                )
            )
            logger.info(f"[TELEGRAM] Initialized (chat_id={config.telegram.chat_id})")

    # Email (always included as fallback)
    notifiers.append(
        EmailNotifier(
            config_path=config.email.config_path,
            priority=config.email.priority,
            enabled=config.email.enabled,
        )
    )
    logger.info(f"[EMAIL] Initialized (config={config.email.config_path})")

    # Sort by priority and filter enabled
    notifiers.sort(key=lambda n: n.priority)
    enabled_notifiers = [n for n in notifiers if n.enabled]

    logger.info(f"Built {len(enabled_notifiers)}/{len(notifiers)} enabled notifiers:")
    for n in enabled_notifiers:
        logger.info(f"  → {n.notifier_type} (priority={n.priority})")

    return enabled_notifiers
