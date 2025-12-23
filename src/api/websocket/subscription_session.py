"""
Subscription-based WebSocket session for PubSub monitoring.
Uses AsyncGenerator pattern to consume PubSub events.
"""

import asyncio
import logging
from typing import Any

from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder

from core.util.pubsub.base import PubSub
from core.util.pubsub.pubsub_topic import PubSubTopic

logger = logging.getLogger(__name__)


class SubscriptionSession:

    SNAPSHOT_KEYS = (
        "device_id",
        "model",
        "slave_id",
        "type",
        "is_online",
        "sampling_datetime",
        "values",
    )

    """
    WebSocket session that subscribes to PubSub DEVICE_SNAPSHOT events.

    Full-duplex:
    - Receive: Subscribe to PubSub snapshots (AsyncGenerator)
    - Send: Handle control commands
    """

    def __init__(self, websocket: WebSocket, pubsub: PubSub, parameter_service=None, device_filter: str | None = None):
        self.websocket = websocket
        self.pubsub = pubsub
        self.parameter_service = parameter_service
        self.device_filter = device_filter
        self._running = False

    async def run(self):
        """Run full-duplex session."""
        await self.websocket.accept()
        self._running = True

        logger.info(f"[Subscription] Started: device_filter={self.device_filter or 'ALL'}")

        try:
            # Create tasks
            subscription_task = asyncio.create_task(self._subscription_loop())
            control_task = asyncio.create_task(self._control_loop())

            # Wait for first task to complete
            _, pending = await asyncio.wait([subscription_task, control_task], return_when=asyncio.FIRST_COMPLETED)

            # Cancel remaining
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        finally:
            self._running = False
            logger.info(f"[Subscription] Ended: device_filter={self.device_filter or 'ALL'}")

    async def _subscription_loop(self):
        """Subscribe to PubSub and forward snapshots to WebSocket."""
        try:
            # Subscribe to DEVICE_SNAPSHOT (AsyncGenerator)
            async for snapshot in self.pubsub.subscribe(PubSubTopic.DEVICE_SNAPSHOT):
                logger.info(f"[Subscription] Received snapshot: {snapshot}")
                if not self._running:
                    break

                if not isinstance(snapshot, dict):
                    logger.warning(f"[Subscription] Invalid snapshot type: {type(snapshot)}")
                    continue

                payload: dict[str, Any] = {key: snapshot[key] for key in self.SNAPSHOT_KEYS if key in snapshot}
                safe_payload = jsonable_encoder(payload)

                # Filter by device_id if specified
                device_id = snapshot.get("device_id")

                if self.device_filter:
                    if device_id != self.device_filter:
                        logger.debug(f"[Subscription] Filtered out: {device_id} != {self.device_filter}")
                        continue

                # Send to WebSocket
                try:
                    await self.websocket.send_json(safe_payload)
                    logger.debug(f"[Subscription] Sent snapshot: {device_id}")
                except Exception as e:
                    logger.warning(f"[Subscription] Failed to send: {e}")
                    break

        except asyncio.CancelledError:
            logger.info("[Subscription] Subscription loop cancelled")
        except Exception as e:
            logger.error(f"[Subscription] Subscription loop error: {e}", exc_info=True)

    async def _control_loop(self):
        """Handle incoming control commands."""
        if not self.parameter_service:
            # Dashboard mode: no control, just keepalive
            while self._running:
                try:
                    await asyncio.sleep(30)
                    await self.websocket.send_json({"type": "keepalive"})
                except Exception:
                    break
            return

        # Full control mode
        while self._running:
            try:
                message = await self.websocket.receive_json()
                action = message.get("action")

                if action == "write":
                    await self._handle_write(message)
                elif action == "ping":
                    await self.websocket.send_json({"type": "pong"})
                else:
                    await self.websocket.send_json({"type": "error", "message": f"Unknown action: {action}"})

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[Subscription] Control loop error: {e}")
                break

    async def _handle_write(self, message: dict):
        """Handle write command."""
        device_id = self.device_filter or message.get("device_id")
        parameter = message.get("parameter")
        value = message.get("value")
        force = message.get("force", False)

        if not device_id or not parameter or value is None:
            await self.websocket.send_json(
                {"type": "write_result", "success": False, "error": "Missing device_id, parameter, or value"}
            )
            return

        try:
            result = await self.parameter_service.write_parameter(
                device_id=device_id, parameter=parameter, value=value, force=force
            )

            await self.websocket.send_json(
                {
                    "type": "write_result",
                    "device_id": device_id,
                    "parameter": parameter,
                    "value": value,
                    "success": result.get("success", False),
                    "was_forced": result.get("was_forced", False),
                    "error": result.get("error"),
                }
            )

        except Exception as e:
            logger.error(f"[Subscription] Write failed: {e}", exc_info=True)
            await self.websocket.send_json(
                {
                    "type": "write_result",
                    "device_id": device_id,
                    "parameter": parameter,
                    "value": value,
                    "success": False,
                    "error": str(e),
                }
            )
