import logging

from core.evaluator.time_evalutor import TimeControlEvaluator
from core.executor.time_control_executor import TimeControlExecutor
from core.schema.control_condition_schema import ControlActionType
from core.util.pubsub.base import PubSub
from core.util.pubsub.pubsub_topic import PubSubTopic

logger = logging.getLogger("TimeControlHandler")


class TimeControlHandler:
    def __init__(
        self,
        pubsub: PubSub,
        time_control_evaluator: TimeControlEvaluator,
        executor: TimeControlExecutor,
        send_turn_off_on_change: bool = True,
        send_turn_on_on_change: bool = True,
        expected_devices: set[str] = None,
    ):
        self.pubsub = pubsub
        self.evaluator = time_control_evaluator
        self.executor = executor
        self.send_turn_off_on_change = send_turn_off_on_change
        self.send_turn_on_on_change = send_turn_on_on_change
        self._expected_devices = set(expected_devices)

        # Active startup tracking
        self._startup_checked = set()
        self._startup_on_list = []
        self._startup_off_list = []
        self._startup_summary_logged = False

    async def handle_snapshot(self, snapshot: dict):
        device_id: str = snapshot.get("device_id")
        if not device_id:
            return

        model, slave_id = device_id.rsplit("_", 1)
        slave_id = int(snapshot.get("slave_id", slave_id))

        action_type = self.evaluator.evaluate_action(device_id)

        # Startup status statistics
        if device_id not in self._startup_checked:
            if action_type == ControlActionType.TURN_OFF:
                self._startup_off_list.append(device_id)
            elif action_type == ControlActionType.TURN_ON:
                self._startup_on_list.append(device_id)
            self._startup_checked.add(device_id)
            self._try_log_startup_summary()

        # Process action based on evaluation
        if action_type == ControlActionType.TURN_OFF and self.send_turn_off_on_change:
            logger.info(f"[{__class__.__name__}] {device_id} off_timezone → skip alerts & controls.")
            await self.executor.send_control(device_id, model, slave_id, action_type, "Off timezone auto shutdown")
            return

        if action_type == ControlActionType.TURN_ON and self.send_turn_on_on_change:
            await self.executor.send_control(device_id, model, slave_id, action_type, "On timezone auto startup")

        # Transmit the snapshot if the device is allowed
        if self.evaluator.allow(device_id):
            await self.pubsub.publish(PubSubTopic.SNAPSHOT_ALLOWED, snapshot)

    def _try_log_startup_summary(self):
        if self._startup_summary_logged:
            return
        if self._expected_devices and not self._expected_devices.issubset(self._startup_checked):
            return
        self._log_startup_summary()

    def _log_startup_summary(self):
        logger.info(
            f"[TimeControl] Startup sync complete: "
            f"{len(self._startup_off_list)} devices turned off ({', '.join(self._startup_off_list) or 'None'}), "
            f"{len(self._startup_on_list)} devices turned on ({', '.join(self._startup_on_list) or 'None'})"
        )
        self._startup_summary_logged = True
