import logging
from datetime import datetime

from core.evaluator.alert_evaluator import AlertEvaluationResult, AlertEvaluator
from core.model.enum.alert_enum import AlertSeverity
from core.model.enum.alert_state_enum import AlertState
from core.schema.alert_schema import AlertMessageModel
from core.util.dashboard_helper import DashboardHelper
from core.util.pubsub.base import PubSub
from core.util.pubsub.pubsub_topic import PubSubTopic
from core.util.snapshot_aggregator import SnapshotAggregator
from core.util.time_util import TIMEZONE_INFO


class AlertEvaluatorSubscriber:
    def __init__(
        self,
        pubsub: PubSub,
        alert_evaluator: AlertEvaluator,
        monitor_interval: float = 10.0,
        eval_interval: float | None = None,
        outlier_log_path: str = "logs/outlier.log",
    ):
        self.pubsub = pubsub
        self.evaluator = alert_evaluator
        self.dashboard_helper = DashboardHelper()
        self.logger = logging.getLogger(__class__.__name__)

        effective_eval = eval_interval if eval_interval is not None else monitor_interval
        self._use_aggregation = effective_eval != monitor_interval

        if self._use_aggregation:
            self._aggregator = SnapshotAggregator(
                monitor_interval=monitor_interval,
                eval_interval=effective_eval,
                outlier_log_path=outlier_log_path,
            )

    async def run(self):
        async for message in self.pubsub.subscribe(PubSubTopic.SNAPSHOT_ALLOWED):
            try:
                model: str = message["model"]
                slave_id: str = message["slave_id"]
                snapshot: dict = message["values"]
                device_id = f"{model}_{slave_id}"

                if self._use_aggregation:
                    await self._handle_with_aggregation(model, slave_id, device_id, snapshot)
                else:
                    await self._handle_direct(model, slave_id, device_id, snapshot)

            except Exception as e:
                self.logger.error(f"{__class__.__name__} failed: {e}", exc_info=True)

    async def _handle_with_aggregation(
        self, model: str, slave_id: str, device_id: str, snapshot: dict[str, float]
    ) -> None:

        self._aggregator.push(device_id, snapshot)

        if self._aggregator.buffer_size(device_id) >= self._aggregator.max_capacity:
            aggregated = self._aggregator.aggregate(device_id)
            self._aggregator.clear(device_id)

            if aggregated is None:
                return  # All outliers for some parameter – skip evaluation

            await self._handle_direct(model, slave_id, device_id, aggregated)

    async def _handle_direct(self, model: str, slave_id: str, device_id: str, snapshot: dict[str, float]) -> None:
        alert_results: list[AlertEvaluationResult] = self.evaluator.evaluate(device_id=device_id, snapshot=snapshot)

        for result in alert_results:
            if result.notification_type == AlertState.RESOLVED.name:
                final_severity = AlertSeverity.RESOLVED
            else:
                final_severity = result.severity

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

            await self.pubsub.publish(PubSubTopic.ALERT_WARNING, alert)
