import asyncio
import logging
import mimetypes
import smtplib
from datetime import datetime
from email.message import EmailMessage
from email.utils import make_msgid

from core.schema.alert_schema import AlertMessageModel
from core.util.config_manager import ConfigManager
from core.util.notifier.base import BaseNotifier
from core.util.time_util import TIMEZONE_INFO


class EmailNotifier(BaseNotifier):
    def __init__(self, config_path: str, priority: int = 3, enabled: bool = True):
        super().__init__(priority=priority, enabled=enabled)
        self.logger = logging.getLogger("EmailNotifier")

        email_cfg: dict = ConfigManager.load_yaml_file(config_path)
        self.smtp_host = ConfigManager.parse_env_var_with_default(email_cfg["SMTP_HOST"])
        self.smtp_port = ConfigManager.parse_env_var_with_default(email_cfg["SMTP_PORT"])
        self.template_path = ConfigManager.parse_env_var_with_default(email_cfg["EMAIL_TEMPLATE_PATH"])
        self.username = ConfigManager.parse_env_var_with_default(email_cfg["SMTP_USERNAME"])
        self.password = ConfigManager.parse_env_var_with_default(email_cfg["SMTP_PASSWORD"])
        self.from_addr = ConfigManager.parse_env_var_with_default(email_cfg["EMAIL_FROM"])
        self.logo_path = ConfigManager.parse_env_var_with_default(email_cfg["EMAIL_LOGO_PATH"])

        self.to_addrs = email_cfg["TO_ADDRESSES"]

    async def send(self, alert: AlertMessageModel) -> bool:
        if not self.enabled:
            self.logger.debug("[EMAIL] Email notifier is disabled, skipping")
            return False

        self.logger.info(f"[EMAIL] Send Email: [{alert.level}] {alert.model} - {alert.message}")

        try:
            loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._send_email_sync, alert)
            self.logger.info(f"[EMAIL] Successfully sent: {alert.alert_code}")
            return True
        except Exception as e:
            self.logger.error(f"[EMAIL] Failed to send: {e}")
            return False

    def _send_email_sync(self, alert: AlertMessageModel):
        with open(self.template_path, "r", encoding="utf-8") as f:
            template = f.read()

        logo_cid: str = make_msgid(domain="ima-ems.com")[1:-1]
        rendered_html = template.format(
            time=datetime.now(TIMEZONE_INFO).strftime("%Y-%m-%d %H:%M:%S"),
            device_model=alert.model,
            slave_id=alert.slave_id,
            level=alert.level,
            message=alert.message,
            logo_cid=logo_cid,
        ).replace("cid:logo_cid", f"cid:{logo_cid}")

        msg = EmailMessage()
        msg["Subject"] = f"[{alert.level.name}] {alert.model}_{alert.slave_id}: {alert.alert_code}"
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.to_addrs)
        msg.set_content("This is an HTML email. Please use an HTML-capable email client.")
        msg.add_alternative(rendered_html, subtype="html")

        with open(self.logo_path, "rb") as img:
            img_data = img.read()
            img_type = mimetypes.guess_type(self.logo_path)[0] or "image/png"
            msg.get_payload()[1].add_related(img_data, maintype="image", subtype=img_type.split("/")[1], cid=logo_cid)

        try:
            with smtplib.SMTP(self.smtp_host, int(self.smtp_port)) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.send_message(msg)
            self.logger.info(f"[EMAIL] Successfully sent email for alert: {alert.alert_code}")
        except Exception as e:
            self.logger.error(f"[EMAIL] Failed to send email: {e}")
