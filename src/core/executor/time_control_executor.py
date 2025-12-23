import logging
from dataclasses import dataclass
from typing import Literal

from core.device.generic.capability import CapabilityResolver, OnOffBinding
from core.schema.control_condition_schema import ControlActionSchema, ControlActionType
from core.util.pubsub.base import PubSub
from core.util.pubsub.pubsub_topic import PubSubTopic

logger = logging.getLogger("TimeControlExecutor")


ActionKind = Literal["turn_on", "turn_off"]


@dataclass(frozen=True)
class _PendingControl:
    device_id: str
    model: str
    slave_id: int
    action_type: ControlActionType
    reason: str


class TimeControlExecutor:
    """
    Time control command emitter with offline-defer support.

    Key behavior:
    - If device is offline, TimeControlHandler should call defer_control() instead of send_control()
    - When device recovers (offline -> online), TimeControlHandler calls on_device_recovered(device_id)
      to flush the deferred action(s).
    - Per-device de-dup: only keep the latest TURN_ON / TURN_OFF (last-write-wins).
    - Flush order: TURN_ON first, then TURN_OFF (in case both were queued).
    """

    def __init__(self, pubsub: PubSub, capability_resolver: CapabilityResolver):
        self.pubsub = pubsub
        self.cap = capability_resolver

        # pending actions: device_id -> {"turn_on": pending, "turn_off": pending}
        self._pending: dict[str, dict[ActionKind, _PendingControl]] = {}

    async def _publish(self, action: ControlActionSchema) -> None:
        await self.pubsub.publish(PubSubTopic.CONTROL, action)

    def _pending_key(self, action_type: ControlActionType) -> ActionKind | None:
        """
        Map ControlActionType to internal ActionKind literal.

        Returns:
            "turn_on" for TURN_ON
            "turn_off" for TURN_OFF
            None for other types
        """
        if action_type == ControlActionType.TURN_ON:
            return "turn_on"
        if action_type == ControlActionType.TURN_OFF:
            return "turn_off"
        return None

    async def defer_control(
        self,
        device_id: str,
        model: str,
        slave_id: int,
        action_type: ControlActionType,
        reason: str,
    ) -> None:
        """
        Record a control request to be sent later when device recovers.
        Only TURN_ON / TURN_OFF are supported for defer (others are unexpected in time control path).
        """
        k = self._pending_key(action_type)
        if k is None:
            logger.warning(f"[TimeControl] {device_id} defer ignored: unsupported action {action_type}")
            return

        per_dev = self._pending.setdefault(device_id, {})
        per_dev[k] = _PendingControl(
            device_id=device_id,
            model=model,
            slave_id=int(slave_id),
            action_type=action_type,
            reason=reason,
        )

        if logger.isEnabledFor(logging.INFO):
            logger.info(f"[TimeControl] {device_id} offline → defer {action_type.name} ({reason})")

    async def on_device_recovered(self, device_id: str) -> None:
        """
        Flush deferred controls for this device (if any).
        Called by TimeControlHandler when offline -> online transition is detected.
        """
        per_dev = self._pending.get(device_id)
        if not per_dev:
            return

        # Flush TURN_ON first, then TURN_OFF
        flush_order: list[ActionKind] = ["turn_on", "turn_off"]
        to_send: list[_PendingControl] = []
        for k in flush_order:
            p = per_dev.get(k)
            if p:
                to_send.append(p)

        # Remove pending before sending to avoid re-entrancy / duplicate flush
        self._pending.pop(device_id, None)

        for p in to_send:
            await self.send_control(
                device_id=p.device_id,
                model=p.model,
                slave_id=p.slave_id,
                action_type=p.action_type,
                reason=f"{p.reason} (flush_on_recovered)",
            )

        if logger.isEnabledFor(logging.INFO):
            logger.info(f"[TimeControl] {device_id} recovered → flushed {len(to_send)} action(s)")

    async def send_control(
        self,
        device_id: str,
        model: str,
        slave_id: int,
        action_type: ControlActionType,
        reason: str,
    ) -> None:
        """
        Routing rules:
          - If the device supports on/off: directly send TURN_ON / TURN_OFF
          - If not supported: use driver/instance on_off_binding to translate into multiple WRITE_DO(target=value)
        """
        # 1) Supports on/off → send as-is
        if self.cap.supports_on_off(model, slave_id):
            await self._publish(
                ControlActionSchema(
                    model=model,
                    slave_id=slave_id,
                    type=action_type,
                    target=None,
                    value=None,
                    action_origin="TimeControl",
                    reason=reason,
                )
            )
            logger.info(f"[TimeControl] {device_id} → {action_type.name} ({reason})")
            return

        # 2) Not supported → attempt to translate into WRITE_DO
        binding: OnOffBinding | None = self.cap.get_on_off_binding(model, slave_id)
        if binding and action_type in (ControlActionType.TURN_ON, ControlActionType.TURN_OFF):
            # Defensive: ensure enum contains WRITE_DO
            if not hasattr(ControlActionType, "WRITE_DO"):
                logger.error("[TimeControl] WRITE_DO not supported by ControlActionType; skip translation.")
                return

            value: int = binding.on if action_type == ControlActionType.TURN_ON else binding.off
            for target in binding.targets:
                await self._publish(
                    ControlActionSchema(
                        model=model,
                        slave_id=slave_id,
                        type=ControlActionType.WRITE_DO,
                        target=target,  # e.g., "DOut01"
                        value=int(value),
                        action_origin="TimeControl",
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
