import logging

from core.evaluator.constraint_evaluator import ConstraintEvaluator
from core.util.pubsub.base import PubSub
from core.util.pubsub.pubsub_topic import PubSubTopic


class ConstraintSubscriber:
    def __init__(self, pubsub: PubSub, evaluator: ConstraintEvaluator):
        self.pubsub = pubsub
        self.evaluator = evaluator
        self.logger = logging.getLogger(__class__.__name__)

    async def run(self):
        async for snapshot in self.pubsub.subscribe(PubSubTopic.SNAPSHOT_ALLOWED):
            device = snapshot.get("device")
            if not device:
                self.logger.warning(f"[{__class__.__name__}] Snapshot missing 'device' key, skip.")
                continue

            await self.evaluator.evaluate(device, snapshot["values"])
