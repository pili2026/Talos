import logging

from generic_device import AsyncGenericModbusDevice
from model.control_model import ControlActionModel, ControlActionType
from util.pubsub.base import PubSub
from util.pubsub.pubsub_topic import PubSubTopic

logger = logging.getLogger("ConstraintEvaluator")


class ConstraintEvaluator:
    def __init__(self, pubsub: PubSub):
        self.pubsub = pubsub

    async def evaluate(self, device: AsyncGenericModbusDevice, snapshot: dict[str, float | int]):
        """
        Evaluate the device snapshot against constraints and publish control actions if needed.
        """
        control_actions = []

        for target, value in snapshot.items():
            if target in device.constraints:
                limit = device.constraints[target]
                min_val: float | int = limit.get("min", 60)
                max_val: float | int = limit.get("max", 60)

                if value < min_val or value > max_val:
                    corrected_value = max(min_val, min(value, max_val))

                    logger.warning(
                        f"[{device.model}_{device.slave_id}] Pin {target} value {value} out of bounds "
                        f"[{min_val}, {max_val}], correcting to {corrected_value}"
                    )

                    control_actions.append(
                        ControlActionModel(
                            model=device.model,
                            slave_id=device.slave_id,
                            type=ControlActionType.SET_FREQUENCY,
                            target=target,
                            value=corrected_value,
                            source=__class__.__name__,
                            reason=f"Value {value} out of range [{min_val}, {max_val}]",
                        )
                    )

        for action in control_actions:
            await self.pubsub.publish(PubSubTopic.CONTROL, action)
