from core.schema.alert_schema import AlertMessageModel
from core.util.locale_manager import LocaleManager
from core.util.notifier.webhook_notifier import WebhookNotifier


class TelegramNotifier(WebhookNotifier):
    """
    Telegram Bot API notifier.
    Inherits WebhookNotifier for HTTP handling.
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        priority: int = 2,
        enabled: bool = True,
        timeout_sec: float = 5.0,
        parse_mode: str = "HTML",
        locale: str = "zh_TW",
    ):
        # Build Telegram API URL
        api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

        super().__init__(
            url=api_url,
            priority=priority,
            enabled=enabled,
            timeout_sec=timeout_sec,
            platform="telegram",
        )
        self.chat_id = chat_id
        self.parse_mode = parse_mode
        self.locale_manager = LocaleManager()
        available = self.locale_manager.get_available_locales()
        if locale not in available:
            raise ValueError(f"Invalid locale '{locale}'. Available: {', '.join(available)}")
        self.locale = locale

    def _build_payload(self, alert: AlertMessageModel) -> dict:
        """Build Telegram sendMessage payload"""
        message = self._format_message(alert)

        return {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": self.parse_mode,
        }

    def _format_message(self, alert: AlertMessageModel) -> str:
        """Format message using locale template"""

        locale_config = self.locale_manager.get_locale(self.locale)

        # Get emoji
        emoji = locale_config.level_emojis.get(alert.level.name, "⚪")

        # Get translated operator
        operator_text = locale_config.operators.get(alert.condition, alert.condition)

        # Get translated level
        level_text = locale_config.level_names.get(alert.level.name, alert.level.name)

        # Format the main message using template
        try:
            main_message = locale_config.message_format.format(
                level=level_text,
                device_name=alert.device_name,
                operator=operator_text,
                threshold=alert.threshold,
                value=alert.current_value,
            )
        except (KeyError, AttributeError):
            # Fallback to alert message if formatting fails
            main_message = alert.message

        # Build the structured message
        labels = locale_config.field_labels

        message_parts = [
            f"{emoji} <b>{main_message}</b>\n",
        ]

        # Add message
        if "message" in labels:
            message_parts.append(f"<b>{labels['message']}:</b> {alert.message}")

        # Add device_name
        if "device" in labels:
            device_info = f"{alert.device_name} <code>({alert.model}_{alert.slave_id})</code>"
            message_parts.append(f"<b>{labels['device']}:</b> {device_info}")

        # Add name
        if "name" in labels:
            message_parts.append(f"<b>{labels['name']}:</b> {alert.name}")

        # Add time
        message_parts.append(f"<b>{labels['time']}:</b> {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")

        # Add alert code
        message_parts.append(f"<b>{labels['alert_code']}:</b> <code>{alert.alert_code}</code>")

        # Add dashboard link if available
        if alert.dashboard_url:
            message_parts.append(
                f"<b>{labels['dashboard_link']}:</b> <a href='{alert.dashboard_url}'>Open Dashboard</a>"
            )

        return "\n".join(message_parts)
