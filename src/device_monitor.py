import asyncio
import logging
from datetime import datetime
from typing import Any

from core.device.generic.generic_device import AsyncGenericModbusDevice
from core.util.device_health_manager import DeviceHealthManager
from core.util.pubsub.base import PubSub
from core.util.pubsub.pubsub_topic import PubSubTopic
from core.util.time_util import TIMEZONE_INFO
from core.util.virtual_device_manager import VirtualDeviceManager
from device_manager import AsyncDeviceManager

logger = logging.getLogger("AsyncDeviceMonitor")


class AsyncDeviceMonitor:
    def __init__(
        self,
        async_device_manager: AsyncDeviceManager,
        pubsub: PubSub,
        interval: float = 1.0,
        health_manager: DeviceHealthManager | None = None,
        virtual_device_manager: VirtualDeviceManager | None = None,
    ):
        self.device_manager = async_device_manager
        self.pubsub = pubsub
        self.interval = interval
        self.health_manager = health_manager or DeviceHealthManager()
        self.virtual_device_manager = virtual_device_manager

        self._recovery_check_interval = 60
        self._last_recovery_check = 0

        # Register all devices for health tracking
        for device in self.device_manager.device_list:
            device_id = f"{device.model}_{device.slave_id}"
            self.health_manager.register_device(device_id)

    async def run(self):
        """Main monitoring loop with health tracking."""
        logger.info("Starting device monitor loop...")

        try:
            while True:
                start_time = asyncio.get_event_loop().time()
                logger.info("[Monitor] Starting new cycle")

                try:
                    snapshots = await self._read_all_devices()
                    logger.info(f"[Monitor] Read {len(snapshots)} snapshots")

                    # Publish snapshots
                    for snapshot in snapshots:
                        await self.pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, snapshot)

                except Exception as e:
                    logger.error(f"Error in monitor loop: {e}", exc_info=True)

                # Calculate sleep time
                elapsed = asyncio.get_event_loop().time() - start_time
                sleep_time = max(0, self.interval - elapsed)

                logger.info(f"[Monitor] Cycle completed in {elapsed:.2f}s, sleeping {sleep_time:.2f}s")
                await asyncio.sleep(sleep_time)

        except asyncio.CancelledError:
            logger.info("Device monitor stopped")
            raise

    async def _read_all_devices(self) -> list[dict[str, Any]]:
        """Read all devices with health tracking."""

        logger.info(f"[Monitor] _read_all_devices() called, devices: {len(self.device_manager.device_list)}")

        snapshots = []
        current_time: float = datetime.now(tz=TIMEZONE_INFO).timestamp()

        should_check_recovery = current_time - self._last_recovery_check > self._recovery_check_interval
        if should_check_recovery:
            logger.info("[Monitor] Performing recovery check for unhealthy devices")
            self._last_recovery_check = current_time

        for device in self.device_manager.device_list:
            device_id = f"{device.model}_{device.slave_id}"
            logger.info(f"[Monitor] Processing device: {device_id}")

            is_healthy = self.health_manager.is_healthy(device_id)
            logger.info(f"[Monitor] {device_id} health status: {is_healthy}")

            # ========== Check health before reading ==========
            if not is_healthy and not should_check_recovery:
                logger.info(f"[Monitor] Skipping unhealthy device: {device_id}")
                snapshot = self._create_offline_snapshot(device_id)
                snapshots.append(snapshot)
                continue

            logger.info(f"[Monitor] Attempting to read {device_id}")
            # ========== Try to read device ==========
            try:
                snapshot: dict[str, Any] = await self._read_device(device)

                # Mark success if got valid data
                if snapshot.get("is_online", False):
                    await self.health_manager.mark_success(device_id)
                else:
                    logger.warning(f"[Monitor] Device {device_id} read failed, marking as unhealthy")
                    await self.health_manager.mark_failure(device_id)

                snapshots.append(snapshot)

            except Exception as e:
                logger.warning(f"[Monitor] Failed to read {device_id}: {e}")
                await self.health_manager.mark_failure(device_id)

                # Create offline snapshot
                snapshot = self._create_offline_snapshot(device_id)
                snapshots.append(snapshot)

        await self._process_virtual_devices(snapshots)

        return snapshots

    async def _read_device(self, device: AsyncGenericModbusDevice) -> dict[str, Any]:
        """Read a single device."""
        device_id: str = f"{device.model}_{device.slave_id}"

        try:
            result = await device.read_all()

            # Check if we got valid data
            is_online: bool = any(v != -1 and v is not None for v in result.values() if isinstance(v, (int, float)))
            logger.info(f"[{device_id}] read_all result: {result}")
            logger.info(f"[{device_id}] is_online: {is_online}")

            return {
                "device_id": device_id,
                "device": device,
                "model": device.model,
                "slave_id": device.slave_id,
                "type": device.device_type,
                "is_online": is_online,
                "sampling_ts": datetime.now(tz=TIMEZONE_INFO),
                "values": result,
            }

        except Exception as e:
            logger.error(f"[Monitor] Error reading {device_id}: {e}")
            raise

    def _create_offline_snapshot(self, device_id: str) -> dict[str, Any]:
        """Create snapshot for offline device."""
        model, slave_id = device_id.rsplit("_", 1)

        device: AsyncGenericModbusDevice | None = self.device_manager.get_device_by_model_and_slave_id(
            model, int(slave_id)
        )
        device_type: str = device.device_type if device else "UNKNOWN"

        return {
            "device_id": device_id,
            "device": device,
            "model": model,
            "slave_id": int(slave_id),
            "type": device_type,
            "is_online": False,
            "sampling_ts": datetime.now(tz=TIMEZONE_INFO),
            "values": {},
            "error": "Device offline or unhealthy",
        }

    async def _process_virtual_devices(self, snapshots: list[dict[str, Any]]) -> None:
        """Process virtual devices and append them to the snapshots list."""
        if not self.virtual_device_manager:
            return

        try:
            # Convert list to dict format, ONLY include online devices
            raw_snapshots_dict = {
                snapshot["device_id"]: snapshot for snapshot in snapshots if snapshot.get("is_online", False)
            }

            # Compute virtual devices
            virtual_snapshots_dict: dict[str, dict] = self.virtual_device_manager.compute_virtual_snapshots(
                raw_snapshots_dict
            )

            if not virtual_snapshots_dict:
                return

            logger.info(
                f"[Monitor] Computed {len(virtual_snapshots_dict)} virtual device(s): {list(virtual_snapshots_dict.keys())}"
            )

            # Convert and append
            for device_id, virtual_snapshot in virtual_snapshots_dict.items():
                virtual_snapshot_full = {
                    "device_id": device_id,
                    "device": None,
                    "model": virtual_snapshot["model"],
                    "slave_id": virtual_snapshot["slave_id"],
                    "type": virtual_snapshot["type"],
                    "is_online": True,
                    "sampling_ts": virtual_snapshot["sampling_ts"],
                    "values": virtual_snapshot["values"],
                    "_is_virtual": True,
                    "_virtual_config_id": virtual_snapshot.get("_virtual_config_id"),
                    "_source_device_ids": virtual_snapshot.get("_source_device_ids", []),
                }
                snapshots.append(virtual_snapshot_full)
                await self.health_manager.mark_success(device_id)

        except Exception as e:
            logger.error(f"[Monitor] Failed to compute virtual devices: {e}", exc_info=True)
