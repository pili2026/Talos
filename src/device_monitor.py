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
    """
    High-performance async device monitor for RS-485 environments.

    Design principles:
    - One RS-485 port == one asyncio.Lock
    - Monitor layer owns the lock (single source of truth)
    - Devices never compete across ports
    - Offline devices are fast-skipped (no I/O)
    """

    def __init__(
        self,
        async_device_manager: AsyncDeviceManager,
        pubsub: PubSub,
        interval: float = 1.0,
        health_manager: DeviceHealthManager | None = None,
        virtual_device_manager: VirtualDeviceManager | None = None,
        *,
        device_timeout_sec: float = 3.0,
        publish_concurrency: int = 50,
        publish_timeout_sec: float | None = None,
        log_each_device: bool = False,
    ):
        self.device_manager = async_device_manager
        self.pubsub = pubsub
        self.interval = float(interval)

        self.health_manager = health_manager or DeviceHealthManager()
        self.virtual_device_manager = virtual_device_manager

        # tuning knobs
        self.device_timeout_sec = float(device_timeout_sec)
        self.publish_concurrency = int(publish_concurrency)
        self.publish_timeout_sec = publish_timeout_sec
        self.log_each_device = bool(log_each_device)

        self._recovery_check_interval = 60.0
        self._last_recovery_check = 0.0

        # health registration
        for device in self.device_manager.device_list:
            device_id = f"{device.model}_{device.slave_id}"
            self.health_manager.register_device(device_id)

        # single source of truth for RS-485 locks
        self._port_locks = self.device_manager._port_locks

    async def run(self):
        if not self.device_manager.device_list:
            logger.warning("[Monitor] No devices configured")

        if not self._port_locks:
            raise RuntimeError("[Monitor] No port locks found; DeviceManager.init() not called?")

        logger.info("=" * 60)
        logger.info("AsyncDeviceMonitor started")
        logger.info(f"Devices: {len(self.device_manager.device_list)}")
        logger.info(f"Ports: {list(self._port_locks.keys())}")
        logger.info(f"Interval: {self.interval}s")
        logger.info("=" * 60)

        try:
            while True:
                loop = asyncio.get_event_loop()
                cycle_start = loop.time()

                try:
                    snapshots = await self._read_all_devices()
                    await self._publish_snapshots(snapshots)
                except Exception as exc:
                    logger.error("[Monitor] Cycle failed", exc_info=exc)

                elapsed = loop.time() - cycle_start
                sleep_time = max(0.0, self.interval - elapsed)

                logger.debug(f"[Monitor] cycle={elapsed:.2f}s sleep={sleep_time:.2f}s")
                await asyncio.sleep(sleep_time)

        except asyncio.CancelledError:
            logger.info("[Monitor] Cancelled")
            raise

    async def _read_all_devices(self) -> list[dict[str, Any]]:
        devices = self.device_manager.device_list
        total = len(devices)

        now_ts = datetime.now(tz=TIMEZONE_INFO).timestamp()
        should_recover = (now_ts - self._last_recovery_check) > self._recovery_check_interval
        if should_recover:
            self._last_recovery_check = now_ts
            logger.debug("[Monitor] Recovery window opened")

        tasks: list[asyncio.Task] = []
        skipped = 0

        for device in devices:
            device_id = f"{device.model}_{device.slave_id}"

            if not self.health_manager.is_healthy(device_id) and not should_recover:
                skipped += 1
                tasks.append(asyncio.create_task(self._offline_snapshot_async(device_id)))
                continue

            tasks.append(asyncio.create_task(self._read_one_device(device, device_id)))

        if skipped:
            logger.debug(f"[Monitor] skipped {skipped}/{total} unhealthy devices")

        results = await asyncio.gather(*tasks, return_exceptions=True)

        snapshots: list[dict[str, Any]] = []
        for idx, r in enumerate(results):
            if isinstance(r, Exception):
                d = devices[idx]
                did = f"{d.model}_{d.slave_id}"
                logger.warning(f"[Monitor] read failed: {did}", exc_info=r)
                snapshots.append(self._create_offline_snapshot(did))
            else:
                snapshots.append(r)

        await self._process_virtual_devices(snapshots)
        return snapshots

    async def _read_one_device(self, device: AsyncGenericModbusDevice, device_id: str) -> dict[str, Any]:
        """
        Read exactly ONE device.
        RS-485 serialization happens here and ONLY here.
        """
        lock = self._port_locks.get(device.port)

        if lock is None:
            logger.error(f"[Monitor] No lock for port={device.port}, reading without lock!")

        try:
            if lock:
                async with lock:
                    result = await asyncio.wait_for(device.read_all(), timeout=self.device_timeout_sec)
            else:
                result = await asyncio.wait_for(device.read_all(), timeout=self.device_timeout_sec)

            is_online = any(v != -1 and v is not None for v in result.values() if isinstance(v, (int, float)))

            if is_online:
                await self.health_manager.mark_success(device_id)
            else:
                await self.health_manager.mark_failure(device_id)

            if self.log_each_device:
                logger.debug(f"[{device_id}] online={is_online}")

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

        except asyncio.TimeoutError:
            logger.warning(f"[Monitor] timeout: {device_id}")
            await self.health_manager.mark_failure(device_id)
            return self._create_offline_snapshot(device_id)

        except Exception as exc:
            logger.warning(f"[Monitor] error reading {device_id}: {exc}")
            await self.health_manager.mark_failure(device_id)
            return self._create_offline_snapshot(device_id)

    async def _publish_snapshots(self, snapshots: list[dict[str, Any]]) -> None:
        if not snapshots:
            return

        sem = asyncio.Semaphore(self.publish_concurrency)

        async def _pub(snap: dict[str, Any]):
            async with sem:
                if self.publish_timeout_sec:
                    await asyncio.wait_for(
                        self.pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, snap),
                        timeout=self.publish_timeout_sec,
                    )
                else:
                    await self.pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, snap)

        results = await asyncio.gather(*(_pub(s) for s in snapshots), return_exceptions=True)

        for idx, r in enumerate(results):
            if isinstance(r, Exception):
                did = snapshots[idx].get("device_id", "unknown")
                logger.warning(f"[Monitor] publish failed: {did}", exc_info=r)

    async def _offline_snapshot_async(self, device_id: str) -> dict[str, Any]:
        return self._create_offline_snapshot(device_id)

    def _create_offline_snapshot(self, device_id: str) -> dict[str, Any]:
        model, slave_id = device_id.rsplit("_", 1)

        device = self.device_manager.get_device_by_model_and_slave_id(model, int(slave_id))
        device_type = device.device_type if device else "UNKNOWN"

        return {
            "device_id": device_id,
            "device": device,
            "model": model,
            "slave_id": int(slave_id),
            "type": device_type,
            "is_online": False,
            "sampling_ts": datetime.now(tz=TIMEZONE_INFO),
            "values": {},
            "error": "offline or unhealthy",
        }

    async def _process_virtual_devices(self, snapshots: list[dict[str, Any]]) -> None:
        if not self.virtual_device_manager:
            return

        online = {s["device_id"]: s for s in snapshots if s.get("is_online")}
        if not online:
            return

        try:
            virtuals = self.virtual_device_manager.compute_virtual_snapshots(online)
            for device_id, v in virtuals.items():
                snapshots.append(
                    {
                        "device_id": device_id,
                        "device": None,
                        "model": v["model"],
                        "slave_id": v["slave_id"],
                        "type": v["type"],
                        "is_online": True,
                        "sampling_ts": v["sampling_ts"],
                        "values": v["values"],
                        "_is_virtual": True,
                        "_virtual_config_id": v.get("_virtual_config_id"),
                        "_source_device_ids": v.get("_source_device_ids", []),
                    }
                )
                await self.health_manager.mark_success(device_id)
        except Exception as exc:
            logger.error("[Monitor] virtual device computation failed", exc_info=exc)
