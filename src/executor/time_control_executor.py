import logging

from model.control_model import ControlActionModel
from util.pubsub.base import PubSub
from util.pubsub.pubsub_topic import PubSubTopic

logger = logging.getLogger("TimeControlExecutor")


class TimeControlExecutor:
    def __init__(self, pubsub: PubSub):
        self.pubsub = pubsub

    async def send_control(self, device_id, model, slave_id, action_type, reason):
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
