import asyncio
import logging

from pydantic import ValidationError

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
        await asyncio.gather(self.run_snapshot_listener(), self.run_control_listener())

    async def run_snapshot_listener(self):
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
                self.logger.warning(f"ControlSubscriber snapshot listener failed: {e}")

    async def run_control_listener(self):
        async for action in self.pubsub.subscribe(PubSubTopic.CONTROL):
            try:
                if isinstance(action, ControlActionModel):
                    control_action = action
                elif isinstance(action, dict):
                    control_action = ControlActionModel(**action)
                else:
                    self.logger.warning(f"Unexpected control action format: {type(action)} → {action}")
                    continue

                self.logger.info(
                    f"[{control_action.model}_{control_action.slave_id}] "
                    f"Apply control from [{control_action.source}]: "
                    f"set {control_action.target} = {control_action.value} "
                    f"({control_action.reason})"
                )

                await self.executor.execute([control_action])

            except ValidationError as ve:
                self.logger.error(f"Invalid ControlActionModel received: {ve}")
            except Exception as e:
                self.logger.warning(f"ControlSubscriber control listener failed: {e}")
