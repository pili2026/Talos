import logging
from datetime import datetime

from evaluator.alert_evaluator import AlertEvaluator
from model.alert_model import AlertMessageModel, AlertSeverity
from util.pubsub.base import PubSub
from util.pubsub.pubsub_topic import PubSubTopic
from util.time_util import TIMEZONE_INFO


class AlertEvaluatorSubscriber:
    def __init__(self, pubsub: PubSub, alert_evaluator: AlertEvaluator):
        self.pubsub = pubsub
        self.evaluator = alert_evaluator
        self.logger = logging.getLogger(__class__.__name__)

    async def run(self):
        async for message in self.pubsub.subscribe(PubSubTopic.SNAPSHOT_ALLOWED):
            try:
                model: str = message["model"]
                slave_id: str = message["slave_id"]
                snapshot: dict = message["values"]

                device_id = f"{model}_{slave_id}"
                alert_list: list[tuple[str, str]] = self.evaluator.evaluate(device_id=device_id, snapshot=snapshot)

                for alert_code, alert_msg in alert_list:
                    alert = AlertMessageModel(
                        model=model,
                        slave_id=slave_id,
                        level=AlertSeverity.WARNING,
                        message=alert_msg,
                        alert_code=alert_code,
                        timestamp=datetime.now(TIMEZONE_INFO),
                    )
                    self.logger.warning(f"[ALERT] [{device_id}] {alert_msg}")
                    await self.pubsub.publish(PubSubTopic.ALERT_WARNING, alert)

            except Exception as e:
                self.logger.warning(f"{__class__.__name__} failed: {e}")
