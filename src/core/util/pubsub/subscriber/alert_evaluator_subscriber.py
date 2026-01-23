import logging
from datetime import datetime

from core.evaluator.alert_evaluator import AlertEvaluationResult, AlertEvaluator
from core.model.enum.alert_enum import AlertSeverity
from core.model.enum.alert_state_enum import AlertState
from core.schema.alert_schema import AlertMessageModel
from core.util.dashboard_helper import DashboardHelper
from core.util.pubsub.base import PubSub
from core.util.pubsub.pubsub_topic import PubSubTopic
from core.util.time_util import TIMEZONE_INFO


class AlertEvaluatorSubscriber:
    def __init__(self, pubsub: PubSub, alert_evaluator: AlertEvaluator):
        self.pubsub = pubsub
        self.evaluator = alert_evaluator
        self.dashboard_helper = DashboardHelper()
        self.logger = logging.getLogger(__class__.__name__)

    async def run(self):
        async for message in self.pubsub.subscribe(PubSubTopic.SNAPSHOT_ALLOWED):
            try:
                model: str = message["model"]
                slave_id: str = message["slave_id"]
                snapshot: dict = message["values"]

                device_id = f"{model}_{slave_id}"

                # Evaluate returns AlertEvaluationResult now
                alert_results: list[AlertEvaluationResult] = self.evaluator.evaluate(
                    device_id=device_id, snapshot=snapshot
                )

                for result in alert_results:
                    # Determine final severity
                    if result.notification_type == AlertState.RESOLVED.name:
                        final_severity = AlertSeverity.RESOLVED
                    else:
                        final_severity = result.severity

                    # Create complete AlertMessageModel
                    alert = AlertMessageModel(
                        model=model,
                        slave_id=int(slave_id),
                        level=final_severity,
                        message=result.message,
                        alert_code=result.alert_code,
                        timestamp=datetime.now(TIMEZONE_INFO),
                        name=result.name,
                        device_name=result.device_name,
                        condition=result.condition,
                        threshold=result.threshold,
                        current_value=result.current_value,
                        dashboard_url=self.dashboard_helper.get_device_url(),
                    )

                    # Log based on notification type and severity
                    if result.notification_type == AlertState.TRIGGERED.name:
                        match result.severity:
                            case AlertSeverity.CRITICAL | AlertSeverity.ERROR:
                                self.logger.error(f"[ALERT] [{device_id}] {result.message}")
                            case AlertSeverity.WARNING:
                                self.logger.warning(f"[ALERT] [{device_id}] {result.message}")
                            case AlertSeverity.INFO:
                                self.logger.info(f"[ALERT] [{device_id}] {result.message}")
                    elif result.notification_type == AlertState.RESOLVED.name:
                        self.logger.info(f"[RESOLVED] [{device_id}] {result.message}")

                    # Publish to notifiers
                    await self.pubsub.publish(PubSubTopic.ALERT_WARNING, alert)

            except Exception as e:
                self.logger.error(f"{__class__.__name__} failed: {e}", exc_info=True)
