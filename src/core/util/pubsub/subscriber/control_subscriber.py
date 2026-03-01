import asyncio
import logging

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
        monitor_interval: float = 10.0,
        eval_interval: float | None = None,
        outlier_log_path: str = "logs/outlier.log",
    ):
        self.pubsub = pubsub
        self.evaluator = evaluator
        self.executor = executor
        self.logger = logging.getLogger(__class__.__name__)

        self._global_snapshot: dict[str, dict[str, float]] = {}

        # Determine effective evaluation interval and whether aggregation is needed
        effective_eval = eval_interval if eval_interval is not None else monitor_interval
        self._use_aggregation = effective_eval != monitor_interval

        if self._use_aggregation:
            self._aggregator = SnapshotAggregator(
                monitor_interval=monitor_interval,
                eval_interval=effective_eval,
                outlier_log_path=outlier_log_path,
            )

    async def run(self):
        """Start both snapshot listener and control action listener concurrently."""
        await asyncio.gather(self.run_snapshot_listener(), self.run_control_listener())

    async def run_snapshot_listener(self):
        """Listen for incoming device snapshots and evaluate control conditions."""
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
        """Handle incoming snapshots by buffering them and evaluating only when the buffer is full."""
        # 1. Push the new snapshot into the aggregator buffer
        self._aggregator.push(device_id, snapshot)

        # 2. Trigger evaluation only when the buffer has collected enough snapshots
        if self._aggregator.buffer_size(device_id) >= self._aggregator.max_capacity:
            aggregated = self._aggregator.aggregate(device_id)
            self._aggregator.clear(device_id)

            if aggregated is None:
                return  # All values for some parameter were outliers – skip evaluation

            # 3. Update global snapshot with the clean, aggregated data and evaluate
            self._global_snapshot[device_id] = aggregated
            control_actions: list[ControlActionSchema] = self.evaluator.evaluate(
                model=model, slave_id=slave_id, snapshot=self._global_snapshot
            )

            if control_actions:
                self.logger.info(f"[{model}] Control actions: {control_actions}")
                await self.executor.execute(control_actions)

    async def run_control_listener(self):
        """Listen for direct control commands from the pubsub broker and execute them."""
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
