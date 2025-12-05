import asyncio
import logging

from core.model.enum.alert_enum import AlertSeverity
from core.schema.alert_schema import AlertMessageModel
from core.schema.notifier_schema import NotificationConfigSchema, NotificationMode, RetryConfigSchema
from core.util.notifier.base import BaseNotifier
from core.util.pubsub.base import PubSub
from core.util.pubsub.pubsub_topic import PubSubTopic


class AlertNotifierSubscriber:
    def __init__(
        self,
        pubsub: PubSub,
        notifier_list: list[BaseNotifier],
        routing_rules: dict[AlertSeverity, dict],
        config_schema: NotificationConfigSchema,
    ):
        self.pubsub = pubsub
        self.notifier_list = notifier_list
        self.routing_rules = routing_rules
        self.config = config_schema
        self.logger = logging.getLogger(__class__.__name__)

        # Build notifier lookup
        self.notifiers_by_type = {
            notifier.notifier_type.lower().replace("notifier", ""): notifier for notifier in notifier_list
        }

        # Log routing configuration
        self._log_routing_config()

    def _log_routing_config(self):
        """Log routing configuration for debugging"""
        self.logger.info("Notification Routing Rules:")
        for severity, rule in self.config.strategy.routing.items():
            self.logger.info(
                f"  {severity.name}: mode={rule.mode.value}, "
                f"notifiers={rule.notifiers}, min_success={rule.min_success}"
            )

    async def run(self):
        async for alert in self.pubsub.subscribe(PubSubTopic.ALERT_WARNING):
            if not isinstance(alert, AlertMessageModel):
                self.logger.warning(f"[SKIP] Invalid alert object: {alert}")
                continue

            await self._route_and_send(alert)

    async def _route_and_send(self, alert: AlertMessageModel):
        """Route alert based on severity"""
        severity = alert.level

        # Get routing rule (type-safe)
        if severity not in self.config.strategy.routing:
            self.logger.warning(f"[ROUTE] No rule for {severity}, using default broadcast")
            await self._send_broadcast(alert, self.notifier_list, min_success=1)
            return

        rule = self.config.strategy.routing[severity]  # ← RoutingRule object

        # Filter target notifiers (type-safe)
        target_notifier_list: list[BaseNotifier] = [
            self.notifiers_by_type[name]
            for name in rule.notifiers
            if name in self.notifiers_by_type and self.notifiers_by_type[name].enabled
        ]

        if not target_notifier_list:
            self.logger.error(f"[ROUTE] No enabled notifiers for {severity}")
            return

        self.logger.info(
            f"[ROUTE] {severity.name} → {rule.mode.value}: " f"{[n.notifier_type for n in target_notifier_list]}"
        )

        # Execute based on mode (enum, not string)
        if rule.mode == NotificationMode.BROADCAST:
            await self._send_broadcast(alert, target_notifier_list, rule.min_success)
        elif rule.mode == NotificationMode.FALLBACK:
            await self._send_fallback(alert, target_notifier_list)
        elif rule.mode == NotificationMode.SINGLE:
            await self._send_single(alert, target_notifier_list)

    async def _send_broadcast(
        self,
        alert: AlertMessageModel,
        notifiers: list[BaseNotifier],
        min_success: int,
    ):
        """Broadcast to all notifiers"""
        tasks = [self._send_with_retry(n, alert) for n in notifiers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        success_count = sum(1 for r in results if r is True)

        if success_count >= min_success:
            self.logger.info(f"[BROADCAST] {success_count}/{len(results)} " f"(required: {min_success})")
        else:
            self.logger.error(f"[BROADCAST] Only {success_count}/{len(results)} " f"(required: {min_success})")

    async def _send_fallback(
        self,
        alert: AlertMessageModel,
        notifiers: list[BaseNotifier],
    ):
        """Fallback chain"""
        for notifier in notifiers:
            success = await self._send_with_retry(notifier, alert)
            if success:
                self.logger.info(f"[FALLBACK] via {notifier.notifier_type}")
                return

        self.logger.error("[FALLBACK] All notifiers failed")

    async def _send_single(
        self,
        alert: AlertMessageModel,
        notifiers: list[BaseNotifier],
    ):
        """Send to first notifier only"""
        if notifiers:
            success: bool = await self._send_with_retry(notifiers[0], alert)
            status: str = "SUCCESS" if success else "FAILURE"
            self.logger.info(f"[SINGLE] {status} via {notifiers[0].notifier_type}")

    async def _send_with_retry(self, notifier: BaseNotifier, alert: AlertMessageModel) -> bool:
        """Send with retry (using config schema)"""
        retry_config: RetryConfigSchema = self.config.retry

        for attempt in range(retry_config.max_attempts):
            try:
                success = await notifier.send(alert)
                if success:
                    return True

                if attempt < retry_config.max_attempts - 1:
                    wait_sec = retry_config.backoff_base_sec * (retry_config.backoff_multiplier**attempt)
                    await asyncio.sleep(wait_sec)

            except Exception as e:
                self.logger.error(f"[{notifier.notifier_type}] Exception: {e}")
                if attempt < retry_config.max_attempts - 1:
                    wait_sec = retry_config.backoff_base_sec * (retry_config.backoff_multiplier**attempt)
                    await asyncio.sleep(wait_sec)

        return False
