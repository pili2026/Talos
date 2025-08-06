import logging

from evaluator.time_evalutor import TimeControlEvaluator
from model.control_model import ControlActionModel, ControlActionType
from util.pubsub.base import PubSub
from util.pubsub.pubsub_topic import PubSubTopic

logger = logging.getLogger("TimeControlSubscriber")


class TimeControlSubscriber:
    def __init__(
        self,
        pubsub: PubSub,
        time_control_evaluator: TimeControlEvaluator,
        send_turn_off_on_change=True,
        send_turn_on_on_change=True,
        expected_devices: list[str] | None = None,
    ):
        self.pubsub = pubsub
        self.time_control_evaluator = time_control_evaluator
        self.send_turn_off_on_change = send_turn_off_on_change
        self.send_turn_on_on_change = send_turn_on_on_change

        # Summary tracking
        self._startup_checked = set()
        self._startup_off_list = []
        self._startup_on_list = []
        self._startup_summary_logged = False
        self._expected_devices = set(expected_devices) if expected_devices else None

    async def run(self):
        async for snapshot in self.pubsub.subscribe(PubSubTopic.DEVICE_SNAPSHOT):
            device_id: str = snapshot.get("device_id")
            if not device_id:
                continue

            model, slave_id = device_id.rsplit("_", 1)
            slave_id = int(snapshot.get("slave_id", slave_id))

            # Evaluate the action type based on the snapshot
            action_type = self.time_control_evaluator.evaluate_action(device_id)

            # First time startup handling
            if device_id not in self._startup_checked:
                if action_type == ControlActionType.TURN_OFF:
                    self._startup_off_list.append(device_id)
                elif action_type == ControlActionType.TURN_ON:
                    self._startup_on_list.append(device_id)
                self._startup_checked.add(device_id)
                self._try_log_startup_summary()

            # Process the action based on the evaluation
            if action_type == ControlActionType.TURN_OFF and self.send_turn_off_on_change:
                logger.info(f"[TimeControl] {device_id} off_timezone → skip alerts & controls.")
                await self._send_control(device_id, model, slave_id, action_type, "Off timezone auto shutdown")
                continue

            if action_type == ControlActionType.TURN_ON and self.send_turn_on_on_change:
                await self._send_control(device_id, model, slave_id, action_type, "On timezone auto startup")

            # If allowed, publish the snapshot
            if self.time_control_evaluator.allow(device_id):
                await self.pubsub.publish(PubSubTopic.SNAPSHOT_ALLOWED, snapshot)

    async def _send_control(self, device_id, model, slave_id, action_type, reason):
        await self.pubsub.publish(
            PubSubTopic.CONTROL,
            ControlActionModel(
                model=model,
                slave_id=slave_id,
                type=action_type,
                target=None,
                value=None,
                source="TimeControl",
                reason=reason,
            ),
        )
        logger.info(f"[TimeControl] {device_id} → sent {action_type.name} ({reason})")

    def _try_log_startup_summary(self):
        if self._startup_summary_logged:
            return
        if self._expected_devices:
            if self._expected_devices.issubset(self._startup_checked):
                self._log_startup_summary()
        else:
            # If no expected devices, log summary when all devices checked
            self._log_startup_summary()

    def _log_startup_summary(self):
        logger.info(
            f"[TimeControl] Startup sync complete: "
            f"{len(self._startup_off_list)} devices turned off ({', '.join(self._startup_off_list) or 'None'}), "
            f"{len(self._startup_on_list)} devices turned on ({', '.join(self._startup_on_list) or 'None'})"
        )
        self._startup_summary_logged = True
