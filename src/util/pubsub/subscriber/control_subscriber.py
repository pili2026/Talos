import logging

from control_evaluator import ControlActionModel, ControlEvaluator
from control_executor import ControlExecutor
from util.pubsub.base import PubSub
from util.pubsub.pubsub_topic import PubSubTopic


class ControlSubscriber:
    def __init__(self, pubsub: PubSub, evaluator: ControlEvaluator, executor: ControlExecutor):
        self.pubsub = pubsub
        self.evaluator = evaluator
        self.executor = executor
        self.logger = logging.getLogger("ControlSubscriber")

    async def run(self):
        async for message in self.pubsub.subscribe(PubSubTopic.DEVICE_SNAPSHOT):
            try:
                model: str = message["model"]
                slave_id: str = message["slave_id"]
                snapshot: dict = message["values"]

                control_actions: list[ControlActionModel] = self.evaluator.evaluate(
                    model=model, slave_id=slave_id, snapshot=snapshot
                )
                if control_actions:
                    self.logger.info(f"[{model}] Control actions: {control_actions}")
                    await self.executor.execute(control_actions)

            except Exception as e:
                self.logger.warning(f"ControlSubscriber failed: {e}")
