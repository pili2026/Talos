import logging

from device.generic.capability import CapabilityResolver, OnOffBinding
from model.control_model import ControlActionModel, ControlActionType
from util.pubsub.base import PubSub
from util.pubsub.pubsub_topic import PubSubTopic

logger = logging.getLogger("TimeControlExecutor")


class TimeControlExecutor:
    def __init__(self, pubsub: PubSub, capability_resolver: CapabilityResolver):
        self.pubsub = pubsub
        self.cap = capability_resolver

    async def _publish(self, action: ControlActionModel):
        await self.pubsub.publish(PubSubTopic.CONTROL, action)

    async def send_control(self, device_id, model, slave_id, action_type, reason):
        """
        Routing rules:
          - If the device supports on/off: directly send TURN_ON / TURN_OFF
          - If not supported: use driver/instance on_off_binding to translate into multiple WRITE_DO(target=value)
        """
        # 1) Supports on/off → send as-is
        if self.cap.supports_on_off(model, slave_id):
            await self._publish(
                ControlActionModel(
                    model=model,
                    slave_id=slave_id,
                    type=action_type,
                    target=None,
                    value=None,
                    source="TimeControl",
                    reason=reason,
                )
            )
            logger.info(f"[TimeControl] {device_id} → {action_type.name} ({reason})")
            return

        # 2) Not supported → attempt to translate into WRITE_DO
        binding: OnOffBinding | None = self.cap.get_on_off_binding(model, slave_id)
        if binding and action_type in (ControlActionType.TURN_ON, ControlActionType.TURN_OFF):
            if not hasattr(ControlActionType, ControlActionType.WRITE_DO.name):
                logger.error("[TimeControl] WRITE_DO not supported by ControlActionType; skip translation.")
                return

            value: int = binding.on if action_type == ControlActionType.TURN_ON else binding.off
            for target in binding.targets:
                await self._publish(
                    ControlActionModel(
                        model=model,
                        slave_id=slave_id,
                        type=ControlActionType.WRITE_DO,
                        target=target,  # e.g., "DOut01"
                        value=int(value),
                        source="TimeControl",
                        reason=f"{reason} -> translate {action_type.name} to {target}={value}",
                    )
                )
            logger.info(
                f"[TimeControl] {device_id} → translate {action_type.name} to WRITE_DO {binding.targets}={value} ({reason})"
            )
            return

        # 3) No capability info → warn and skip
        logger.warning(
            f"[TimeControl] {device_id}({model}) can't handle {action_type.name}: no on/off support or binding."
        )
