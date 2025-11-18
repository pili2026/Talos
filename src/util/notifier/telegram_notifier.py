from schema.alert_schema import AlertMessageModel
from util.notifier.webhook_notifier import WebhookNotifier


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

    def _build_payload(self, alert: AlertMessageModel) -> dict:
        """Build Telegram sendMessage payload"""

        message = self._format_message(alert)

        return {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": self.parse_mode,
        }

    def _format_message(self, alert: AlertMessageModel) -> str:
        """Format message in HTML for Telegram"""

        emoji_map = {
            "CRITICAL": "🔴",
            "ERROR": "🟠",
            "WARNING": "🟡",
            "INFO": "🔵",
            "RESOLVED": "✅",
        }

        emoji = emoji_map.get(alert.level.name, "⚪")

        message = (
            f"{emoji} <b>[{alert.level.name}] Alert</b>\n\n"
            f"<b>Device:</b> <code>{alert.model}_{alert.slave_id}</code>\n"
            f"<b>Alert Code:</b> <code>{alert.alert_code}</code>\n"
            f"<b>Message:</b> {alert.message}\n"
            f"<b>Time:</b> {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"<i>Talos Alert System</i>"
        )

        return message
