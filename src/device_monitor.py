import asyncio
import logging
from datetime import datetime
from typing import Any

from core.device.generic.generic_device import AsyncGenericModbusDevice
from core.model.device_constant import DEFAULT_MISSING_VALUE
from core.schema.health_check_config_schema import HealthCheckConfig
from core.util.device_health_manager import DeviceHealthManager, DeviceHealthStatus
from core.util.pubsub.base import PubSub
from core.util.pubsub.pubsub_topic import PubSubTopic
from core.util.time_util import TIMEZONE_INFO, now_timestamp
from core.util.virtual_device_manager import VirtualDeviceManager
from device_manager import AsyncDeviceManager

logger = logging.getLogger("AsyncDeviceMonitor")


class AsyncDeviceMonitor:
    """
    Stable cadence monitor (worker-pool model)

    Guarantees:
    - Fixed number of reader tasks (no task storm)
    - Offline fast-skip
    - Bounded timeout per device
    - Non-blocking publish
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
        read_concurrency: int = 20,
        publish_concurrency: int = 50,
        recovery_check_interval_sec: float = 60.0,
        critical_recovery_interval_sec: float = 10.0,
        log_each_device: bool = False,
    ):
        self.device_manager = async_device_manager
        self.pubsub = pubsub
        self.interval = float(interval)

        self.health_manager = health_manager or DeviceHealthManager()
        self.virtual_device_manager = virtual_device_manager

        self.device_timeout_sec = float(device_timeout_sec)
        self.read_concurrency = int(read_concurrency)
        self.publish_concurrency = int(publish_concurrency)
        self.log_each_device = bool(log_each_device)

        self._recovery_check_interval = float(recovery_check_interval_sec)
        self._last_recovery_check = 0.0

        self._critical_recovery_interval = float(critical_recovery_interval_sec)
        self._last_critical_recovery_check = 0.0

        self._critical_device_ids = {
            f"{device.model}_{device.slave_id}"
            for device in self.device_manager.device_list
            if device.device_type in health_manager.CRITICAL_DEVICE_TYPES
        }

        logger.info(
            f"Critical devices (fast recovery={critical_recovery_interval_sec}s): "
            f"{', '.join(self._critical_device_ids) if self._critical_device_ids else 'None'}"
        )

        for device in self.device_manager.device_list:
            device_id: str = f"{device.model}_{device.slave_id}"
            device_type: str = device.device_type
            self.health_manager.register_device(device_id, device_type=device_type)

        self._queue: asyncio.Queue[AsyncGenericModbusDevice] = asyncio.Queue()

    # ------------------------------------------------------------------

    async def run(self) -> None:
        if not self.device_manager.device_list:
            logger.warning("[Monitor] No devices configured")

        logger.info("=" * 60)
        logger.info("AsyncDeviceMonitor started (worker-pool)")
        logger.info(f"Devices: {len(self.device_manager.device_list)}")
        logger.info(f"Read concurrency: {self.read_concurrency}")
        logger.info(f"Publish concurrency: {self.publish_concurrency}")
        logger.info(f"Interval: {self.interval}s")
        logger.info("=" * 60)

        workers = [asyncio.create_task(self._reader_worker(i)) for i in range(self.read_concurrency)]

        try:
            while True:
                cycle_start = asyncio.get_running_loop().time()

                snapshots = await self._run_one_cycle()
                await self._publish_snapshots(snapshots)

                elapsed = asyncio.get_running_loop().time() - cycle_start
                sleep_time = max(0.0, self.interval - elapsed)
                logger.debug(f"[Monitor] cycle={elapsed:.2f}s sleep={sleep_time:.2f}s")
                await asyncio.sleep(sleep_time)

        except asyncio.CancelledError:
            logger.info("[Monitor] Cancelled")
            raise
        finally:
            for worker in workers:
                worker.cancel()

    # ------------------------------------------------------------------
    async def _run_one_cycle(self) -> list[dict[str, Any]]:
        """
        Run one monitoring cycle with sequential device processing per port.

        Critical for RS-485: Devices on same port must be processed sequentially
        with delay to prevent response frame confusion.
        """
        device_list: list[AsyncGenericModbusDevice] = self.device_manager.device_list
        now_ts: float = now_timestamp()

        should_recover: bool = (now_ts - self._last_recovery_check) > self._recovery_check_interval
        if should_recover:
            self._last_recovery_check = now_ts
            logger.debug("[Monitor] Recovery window opened")

        critical_should_recover: bool = (now_ts - self._last_critical_recovery_check) > self._critical_recovery_interval
        if critical_should_recover:
            self._last_critical_recovery_check = now_ts
            logger.debug("[Monitor] Critical recovery window opened (inverters)")

        result_map: dict[str, dict[str, Any]] = {}

        # Group devices by port (critical for RS-485)
        devices_by_port: dict[str, list] = {}
        for device in device_list:
            port: str = device.port
            if port not in devices_by_port:
                devices_by_port[port] = []
            devices_by_port[port].append(device)

        # Process devices sequentially per port with delay
        for port, port_devices in devices_by_port.items():
            logger.debug(f"[Monitor] Processing {len(port_devices)} devices on port {port}")

            for i, device in enumerate(port_devices):
                device_id = f"{device.model}_{device.slave_id}"
                is_critical = device_id in self._critical_device_ids
                recovery_window = critical_should_recover if is_critical else should_recover

                await self._queue.put((device, recovery_window, result_map))
                await self._queue.join()

                if i < len(port_devices) - 1:
                    await asyncio.sleep(0.15)

        snapshots: list[dict[str, Any]] = list(result_map.values())
        await self._process_virtual_devices(snapshots)
        return snapshots

    async def _reader_worker(self, worker_id: int) -> None:
        while True:
            device, should_recover, result_map = await self._queue.get()
            device_id = f"{device.model}_{device.slave_id}"

            try:
                snapshot: dict = await self.__get_snapshot_for_device(device, device_id, should_recover)
                logger.info(f"[{device_id}] Snapshot: {snapshot['values']}")
                result_map[device_id] = snapshot

            except Exception as exc:
                logger.warning(f"[Worker-{worker_id}] read failed: {device_id}", exc_info=exc)
                result_map[device_id] = self._create_offline_snapshot(device_id, error="worker exception")

            finally:
                self._queue.task_done()

    async def _read_one_device(self, device: AsyncGenericModbusDevice, device_id: str) -> dict[str, Any]:
        health_status: DeviceHealthStatus | None = self.health_manager._health_status.get(device_id)
        has_recent_failures = (
            health_status
            and health_status.consecutive_failures > 0  # Has failed before
            and health_status.last_failure_ts
            and (now_timestamp() - health_status.last_failure_ts) < 300  # Failed within 5 minutes
        )

        # If has recent failure history, do quick health check first
        if has_recent_failures:
            health_check_config: HealthCheckConfig | None = self.health_manager._health_check_configs.get(device_id)
            if health_check_config:
                try:
                    is_online, health_result = await self.health_manager.quick_health_check(
                        device=device, device_id=device_id
                    )

                    if not is_online:
                        # Quick detection: device is offline
                        await self.health_manager.mark_failure(device_id)
                        logger.debug(
                            f"[{device_id}] Detected offline via adaptive health check "
                            f"(check: {health_result.elapsed_ms:.0f}ms, "
                            f"consecutive_failures: {health_status.consecutive_failures})"
                        )
                        return self._create_offline_snapshot(device_id, error="adaptive_health_check_failed")

                except Exception as exc:
                    logger.debug(f"[{device_id}] Adaptive health check error: {exc}")
                    # Continue to try read_all

        try:
            values: dict[str, Any] = await asyncio.wait_for(device.read_all(), timeout=self.device_timeout_sec)

            is_online: bool = any(
                v != DEFAULT_MISSING_VALUE and v is not None for v in values.values() if isinstance(v, (int, float))
            )

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
                "sampling_datetime": datetime.now(tz=TIMEZONE_INFO),
                "values": values,
            }

        except asyncio.TimeoutError:
            await self.health_manager.mark_failure(device_id)
            return self._create_offline_snapshot(device_id, error="timeout")

        except Exception as exc:
            await self.health_manager.mark_failure(device_id)
            return self._create_offline_snapshot(device_id, error=str(exc))

    async def _publish_snapshots(self, snapshots: list[dict[str, Any]]) -> None:
        if not snapshots:
            return

        sem = asyncio.Semaphore(self.publish_concurrency)

        async def _pub(s: dict[str, Any]) -> None:
            async with sem:
                await self.pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, s)

        results = await asyncio.gather(*(_pub(s) for s in snapshots), return_exceptions=True)

        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                did = snapshots[idx].get("device_id", "unknown")
                logger.warning(f"[Monitor] publish failed: {did}", exc_info=result)

    def _create_offline_snapshot(self, device_id: str, error: str = "offline") -> dict[str, Any]:
        model, slave_id_str = device_id.rsplit("_", 1)
        try:
            slave_id = int(slave_id_str)
        except Exception:
            slave_id = -1

        device = self.device_manager.get_device_by_model_and_slave_id(model, slave_id)
        device_type = device.device_type if device else "UNKNOWN"

        values: dict[str, Any] = {}
        if device and device.register_map:
            for name, cfg in device.register_map.items():
                if cfg.get("readable"):
                    values[name] = DEFAULT_MISSING_VALUE

        return {
            "device_id": device_id,
            "device": device,
            "model": model,
            "slave_id": slave_id,
            "type": device_type,
            "is_online": False,
            "sampling_datetime": datetime.now(tz=TIMEZONE_INFO),
            "values": values,
            "error": error,
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
                        "sampling_datetime": v["sampling_datetime"],
                        "values": v["values"],
                        "_is_virtual": True,
                        "_virtual_config_id": v.get("_virtual_config_id"),
                        "_source_device_ids": v.get("_source_device_ids", []),
                    }
                )
                await self.health_manager.mark_success(device_id)
        except Exception as exc:
            logger.error("[Monitor] virtual device computation failed", exc_info=exc)

    async def __get_snapshot_for_device(self, device, device_id: str, should_recover: bool):
        # 0) Global gate (prevents full read storms)
        allowed, reason = await self.health_manager.should_poll(device_id)
        if not allowed:
            return self._create_offline_snapshot(device_id, error=reason)

        # 1) Healthy: normal full read
        if self.health_manager.is_healthy(device_id):
            return await self._read_one_device(device, device_id)

        # 2) Unhealthy and not recovery: do NOT probe every cycle
        if not should_recover:
            return self._create_offline_snapshot(device_id, error="cooldown")

        # 3) Unhealthy and recovery window: quick check then full read
        is_online, health_result = await self.health_manager.quick_health_check(device=device, device_id=device_id)
        if not is_online:
            return self._create_offline_snapshot(device_id, error="health_check_failed")

        if health_result and logger.isEnabledFor(logging.INFO):
            logger.info(
                f"[{device_id}] ✓ Recovered "
                f"(check: {health_result.elapsed_ms:.0f}ms, strategy: {health_result.strategy})"
            )

        return await self._read_one_device(device, device_id)
