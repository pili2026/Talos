import logging
import smtplib
import time
from collections import defaultdict
from email.message import EmailMessage

from model.alert_message import AlertMessage
from util.config_loader import ConfigManager
from util.pubsub.base import PubSub


class EmailNotifier:
    def __init__(self, pubsub: PubSub, config_path: str = "res/email_config.yml", threshold_sec: float = 60.0):
        self.pubsub = pubsub
        self.logger = logging.getLogger("EmailNotifier")
        self.threshold_sec = threshold_sec
        self.last_sent: dict[tuple[str, str], float] = defaultdict(lambda: 0.0)

        email_cfg: dict = ConfigManager.load_yaml_file(config_path)
        self.smtp_host = ConfigManager.parse_env_var_with_default(email_cfg["smtp_host"])
        self.smtp_port = ConfigManager.parse_env_var_with_default(email_cfg["smtp_port"])
        self.template_path = ConfigManager.parse_env_var_with_default(email_cfg.get("EMAIL_TEMPLATE_PATH"))
        self.username = ConfigManager.parse_env_var_with_default(email_cfg["username"])
        self.password = ConfigManager.parse_env_var_with_default(email_cfg["password"])
        self.from_addr = ConfigManager.parse_env_var_with_default(email_cfg["from_addr"])
        self.to_addrs = email_cfg["to_addrs"]

    async def run(self):
        async for alert in self.pubsub.subscribe("alert.warning"):
            await self.send_email(alert)

    async def send_email(self, alert: AlertMessage):
        key = (alert.device_key, alert.message)
        now = time.time()

        if now - self.last_sent[key] < self.threshold_sec:
            self.logger.info(f"[EMAIL] Skip Duplicate Alert Notification: [{alert.device_key}] {alert.message}")
            return

        self.last_sent[key] = now
        self.logger.info(f"[EMAIL] Send Email: [{alert.level}] {alert.device_key} - {alert.message}")

        self.__send_email(alert)

    def __send_email(self, alert: AlertMessage):
        with open(self.template_path, "r", encoding="utf-8") as f:
            template = f.read()

        rendered_html = template.format(
            time=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            device_key=alert.device_key,
            level=alert.level,
            message=alert.message,
        )

        msg = EmailMessage()
        msg["Subject"] = f"[{alert.level}] Alert from {alert.device_key}"
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.to_addrs)
        msg.set_content("This is an HTML email. Please use an HTML-capable email client.")
        msg.add_alternative(rendered_html, subtype="html")  # HTML part

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.send_message(msg)
                self.logger.info("HTML email sent successfully.")
        except Exception as e:
            self.logger.error(f"Failed to send email: {e}")
