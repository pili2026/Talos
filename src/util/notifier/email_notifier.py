import asyncio
import logging
import mimetypes
import smtplib
from collections import defaultdict
from datetime import datetime
from email.message import EmailMessage
from email.utils import make_msgid

from model.alert_model import AlertMessageModel
from util.config_manager import ConfigManager
from util.notifier.base import BaseNotifier
from util.time_util import TIMEZONE_INFO


class EmailNotifier(BaseNotifier):
    def __init__(self, config_path: str, threshold_sec: float = 60.0):
        self.logger = logging.getLogger("EmailNotifier")
        self.threshold_sec = threshold_sec
        self.last_sent: dict[tuple[str, str], float] = defaultdict(lambda: 0.0)

        email_cfg: dict = ConfigManager.load_yaml_file(config_path)
        self.smtp_host = ConfigManager.parse_env_var_with_default(email_cfg["SMTP_HOST"])
        self.smtp_port = ConfigManager.parse_env_var_with_default(email_cfg["SMTP_PORT"])
        self.template_path = ConfigManager.parse_env_var_with_default(email_cfg.get("EMAIL_TEMPLATE_PATH"))
        self.username = ConfigManager.parse_env_var_with_default(email_cfg["SMTP_USERNAME"])
        self.password = ConfigManager.parse_env_var_with_default(email_cfg["SMTP_PASSWORD"])
        self.from_addr = ConfigManager.parse_env_var_with_default(email_cfg["EMAIL_FROM"])
        self.logo_path = ConfigManager.parse_env_var_with_default(email_cfg["EMAIL_LOGO_PATH"])

        self.to_addrs = email_cfg["TO_ADDRESSES"]

    async def send(self, alert: AlertMessageModel):
        key = (alert.model, alert.message)
        datetime_now: float = datetime.now(TIMEZONE_INFO).timestamp()

        if datetime_now - self.last_sent[key] < self.threshold_sec:
            self.logger.info(f"[EMAIL] Skip Duplicate Alert Notification: [{alert.model}] {alert.message}")
            return

        self.last_sent[key] = datetime_now
        self.logger.info(f"[EMAIL] Send Email: [{alert.level}] {alert.model} - {alert.message}")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._send_email_sync, alert)

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
        msg["Subject"] = f"[{alert.level}] Alert from {alert.model}"
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.to_addrs)
        msg.set_content("This is an HTML email. Please use an HTML-capable email client.")
        msg.add_alternative(rendered_html, subtype="html")  # HTML part

        try:
            with open(self.logo_path, "rb") as img:
                img_data: bytes = img.read()
                mime_type: str = mimetypes.guess_type(self.logo_path)[0] or "application/octet-stream"
                maintype, subtype = mime_type.split("/")
                html_part = msg.get_payload()[1]
                html_part.add_related(img_data, maintype=maintype, subtype=subtype, cid=logo_cid)
        except Exception as e:
            self.logger.warning(f"Logo image not attached: {e}")

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.send_message(msg)
                self.logger.info("HTML email sent successfully.")
        except Exception as e:
            self.logger.error(f"Failed to send email: {e}")
