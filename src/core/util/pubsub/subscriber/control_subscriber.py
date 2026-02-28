import asyncio
import logging
import time as time_module

from pydantic import ValidationError

from core.evaluator.control_evaluator import ControlEvaluator
from core.executor.control_executor import ControlExecutor
from core.schema.control_condition_schema import ControlActionSchema
from core.util.pubsub.base import PubSub
from core.util.pubsub.pubsub_topic import PubSubTopic
from core.util.snapshot_aggregator import SnapshotAggregator


class ControlSubscriber:
    def __init__(
        self,
        pubsub: PubSub,
        evaluator: ControlEvaluator,
        executor: ControlExecutor,
        monitor_interval: float = 1.0,
        eval_interval: float | None = None,
        outlier_log_path: str = "logs/outlier.log",
    ):
        self.pubsub = pubsub
        self.evaluator = evaluator
        self.executor = executor
        self.logger = logging.getLogger(__class__.__name__)

        self._global_snapshot: dict[str, dict[str, float]] = {}

        effective_eval = eval_interval if eval_interval is not None else monitor_interval
        self._use_aggregation = effective_eval != monitor_interval
        self._eval_interval = effective_eval

        if self._use_aggregation:
            self._aggregator = SnapshotAggregator(
                monitor_interval=monitor_interval,
                eval_interval=effective_eval,
                outlier_log_path=outlier_log_path,
            )
            self._last_evaluated_at: float = 0.0

    async def run(self):
        await asyncio.gather(self.run_snapshot_listener(), self.run_control_listener())

    async def run_snapshot_listener(self):
        async for message in self.pubsub.subscribe(PubSubTopic.SNAPSHOT_ALLOWED):
            try:
                model: str = message["model"]
                slave_id: str = message["slave_id"]
                snapshot: dict = message["values"]

                device_id = f"{model}_{slave_id}"

                if self._use_aggregation:
                    await self._handle_with_aggregation(model, slave_id, device_id, snapshot)
                else:
                    self._global_snapshot[device_id] = snapshot
                    control_actions: list[ControlActionSchema] = self.evaluator.evaluate(
                        model=model, slave_id=slave_id, snapshot=self._global_snapshot
                    )
                    if control_actions:
                        self.logger.info(f"[{model}] Control actions: {control_actions}")
                        await self.executor.execute(control_actions)

            except Exception as e:
                self.logger.warning(f"{__class__.__name__} snapshot listener failed: {e}")

    async def _handle_with_aggregation(
        self, model: str, slave_id: str, device_id: str, snapshot: dict[str, float]
    ) -> None:
        now = time_module.monotonic()
        self._aggregator.push(device_id, snapshot)

        if now - self._last_evaluated_at >= self._eval_interval:
            aggregated = self._aggregator.aggregate(device_id)
            self._aggregator.clear(device_id)
            self._last_evaluated_at = now

            if aggregated is None:
                return  # All outliers for some parameter – skip evaluation

            self._global_snapshot[device_id] = aggregated
            control_actions: list[ControlActionSchema] = self.evaluator.evaluate(
                model=model, slave_id=slave_id, snapshot=self._global_snapshot
            )
            if control_actions:
                self.logger.info(f"[{model}] Control actions: {control_actions}")
                await self.executor.execute(control_actions)

    async def run_control_listener(self):
        async for control_action in self.pubsub.subscribe(PubSubTopic.CONTROL):
            try:
                self.logger.info(
                    f"[{control_action.model}_{control_action.slave_id}] "
                    f"Apply control from [{control_action.action_origin}]: "
                    f"set {control_action.target} = {control_action.value} "
                    f"({control_action.reason})"
                )

                await self.executor.execute([control_action])

            except ValidationError as ve:
                self.logger.error(f"Invalid ControlActionModel received: {ve}")
            except Exception as e:
                self.logger.warning(f"ControlSubscriber control listener failed: {e}")
