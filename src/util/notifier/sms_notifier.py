# TODO:  STUB IMPLEMENTATION
import logging

from schema.alert_schema import AlertMessageModel
from util.notifier.base import BaseNotifier


class SmsNotifier(BaseNotifier):
    """
    SMS notification via Twilio/AWS SNS.
    Currently a stub implementation.
    """

    def __init__(
        self,
        phone_numbers: list[str],
        priority: int = 1,
        enabled: bool = False,
    ):
        super().__init__(priority=priority, enabled=enabled)
        self.logger = logging.getLogger("SmsNotifier")
        self.phone_numbers = phone_numbers

    async def send(self, alert: AlertMessageModel) -> bool:
        if not self.enabled:
            self.logger.debug("[SMS] SMS notifier is disabled, skipping")
            return False

        try:
            message = (
                f"[{alert.level.name}] Alert\n"
                f"Device: {alert.model}_{alert.slave_id}\n"
                f"Code: {alert.alert_code}\n"
                f"Message: {alert.message}"
            )

            self.logger.info(f"[SMS] Would send to {self.phone_numbers}: {message}")

            # TODO: Integrate with Twilio/AWS SNS
            # from twilio.rest import Client
            # client = Client(account_sid, auth_token)
            # for phone in self.phone_numbers:
            #     message = client.messages.create(
            #         body=message,
            #         from_=from_number,
            #         to=phone
            #     )

            # For POC: return False to test fallback
            self.logger.warning("[SMS] SMS integration not implemented, returning False")
            return False

        except Exception as e:
            self.logger.error(f"[SMS] Failed to send SMS: {e}")
            return False
