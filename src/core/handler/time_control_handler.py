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
        self._expected_devices = set(expected_devices or [])

        # Active startup tracking
        self._startup_checked = set()
        self._startup_on_list = []
        self._startup_off_list = []
        self._startup_summary_logged = False

        self._last_online: dict[str, bool] = {}

    async def handle_snapshot(self, snapshot: dict):
        device_id: str = snapshot.get("device_id")
        if not device_id:
            return

        model, slave_id = device_id.rsplit("_", 1)
        slave_id = int(snapshot.get("slave_id", slave_id))

        action_type = self.evaluator.evaluate_action(device_id)

        is_online = self._parse_is_online(snapshot)

        was_online = self._last_online.get(device_id)
        self._last_online[device_id] = is_online

        if was_online is False and is_online is True:
            await self.executor.on_device_recovered(device_id)

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
            if is_online:
                await self.executor.send_control(device_id, model, slave_id, action_type, "Off timezone auto shutdown")
            else:
                await self.executor.defer_control(device_id, model, slave_id, action_type, "Off timezone auto shutdown")
            return

        if action_type == ControlActionType.TURN_ON and self.send_turn_on_on_change:
            if is_online:
                await self.executor.send_control(device_id, model, slave_id, action_type, "On timezone auto startup")
            else:
                await self.executor.defer_control(device_id, model, slave_id, action_type, "On timezone auto startup")

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

    def _parse_is_online(self, snapshot: dict) -> bool:
        v = snapshot.get("is_online", snapshot.get("online", snapshot.get("isOnline", None)))
        if v is None:
            # 建議：未知就當 offline，才能符合「先跑 talos 再開機」這種情境
            return False
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return v != 0
        if isinstance(v, str):
            s = v.strip().lower()
            if s in ("1", "true", "yes", "y", "on"):
                return True
            if s in ("0", "false", "no", "n", "off", ""):
                return False
        # fallback：保守起見當 offline
        return False
