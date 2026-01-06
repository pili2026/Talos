import asyncio
import json
import logging
import os
import re
import socket
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import aiofiles
import httpx

from core.model.enum.equipment_enum import EquipmentType
from core.schema.sender_schema import SenderSchema
from core.schema.system_config_schema import RemoteAccessConfig, ReverseSshConfig, SystemConfig
from core.sender.legacy.legacy_format_adapter import convert_snapshot_to_legacy_payload
from core.sender.outbox_store import OutboxStore
from core.sender.transport import ResendTransport
from core.util.system_info.system_info_collector import SystemInfoCollector
from core.util.time_util import TIMEZONE_INFO
from device_manager import AsyncDeviceManager

logger = logging.getLogger("LegacySender")


# TODO: Need to Refactor
class LegacySenderAdapter:

    def __init__(
        self,
        sender_config_schema: SenderSchema,
        device_manager: AsyncDeviceManager,
        series_number: int,
        system_config: SystemConfig,
    ):
        self.sender_config_model = sender_config_schema
        self.gateway_id = self._resolve_gateway_id(self.sender_config_model.gateway_id)
        self.resend_dir = self.sender_config_model.resend_dir
        self.ima_url = self.sender_config_model.cloud.ima_url

        self.send_interval_sec = float(self.sender_config_model.send_interval_sec)
        self.anchor_offset_sec = float(self.sender_config_model.anchor_offset_sec)
        self.tick_grace_sec = float(self.sender_config_model.tick_grace_sec)
        self.fresh_window_sec = float(self.sender_config_model.fresh_window_sec)
        self.last_known_ttl_sec = float(self.sender_config_model.last_known_ttl_sec or 0.0)

        self.fail_resend_enabled = bool(self.sender_config_model.fail_resend_enabled)
        self.fail_resend_interval_sec = int(self.sender_config_model.fail_resend_interval_sec)
        self.fail_resend_batch = int(self.sender_config_model.fail_resend_batch)
        self.last_post_ok_within_sec = float(self.sender_config_model.last_post_ok_within_sec)
        self.resend_start_delay_sec = int(self.sender_config_model.resend_start_delay_sec)

        self.device_manager = device_manager
        os.makedirs(self.resend_dir, exist_ok=True)

        self.__attempt_count = int(self.sender_config_model.attempt_count)
        self.__max_retry = int(self.sender_config_model.max_retry)

        # window → { device_id → snapshot }; in-memory cache only
        self._latest_per_window: dict[datetime, dict[str, dict]] = defaultdict(dict)
        self._lock = asyncio.Lock()
        self._epoch = datetime(1970, 1, 1, tzinfo=TIMEZONE_INFO)

        # ---- Warm-up state ----
        self._first_snapshot_event = asyncio.Event()
        self._first_send_done = False

        # ---- De-dup tracker ----
        self.__last_sent_ts_by_device: dict[str, datetime] = {}
        self.__last_label_ts_by_device: dict[str, datetime] = {}

        # ---- Storage limits (delegate to store) ----
        self.resend_quota_mb = self.sender_config_model.resend_quota_mb
        self.fs_free_min_mb = self.sender_config_model.fs_free_min_mb

        # ---- Shared HTTP client & last success time ----
        self._client: httpx.AsyncClient | None = None
        self._transport: ResendTransport | None = None
        self.last_post_ok_at: datetime | None = None

        # ---- Background worker state ----
        self._resend_task: asyncio.Task | None = None
        self._resend_wakeup: asyncio.Event = asyncio.Event()
        self._stopping: bool = False

        # ---- Main tasks handles (IMPORTANT) ----
        self._warmup_task: asyncio.Task | None = None
        self._scheduler_task: asyncio.Task | None = None

        # ---- Outbox store ----
        self._store = OutboxStore(
            dirpath=self.resend_dir,
            tz=TIMEZONE_INFO,
            gateway_id=self.gateway_id,
            resend_quota_mb=self.resend_quota_mb,
            fs_free_min_mb=self.fs_free_min_mb,
            protect_recent_sec=self.sender_config_model.resend_protect_recent_sec,
            cleanup_batch=self.sender_config_model.resend_cleanup_batch,
            cleanup_enabled=self.sender_config_model.resend_cleanup_enabled,
        )

        self.series_number = series_number
        self.resend_anchor_offset_sec = int(sender_config_schema.resend_anchor_offset_sec)

        self._system_config = system_config

        try:
            self._system_info = SystemInfoCollector()
            logger.info("[LegacySender] System info collector initialized")
            self._system_info.increment_reboot_count()
        except Exception as e:
            logger.error(f"[LegacySender] Failed to initialize SystemInfoCollector: {e}")
            raise

    # -------------------------
    # Public API
    # -------------------------
    async def handle_snapshot(self, snapshot_map: dict) -> None:
        """
        On receiving a snapshot, place it into the bucket of its window
        (within the same window keep only the last one per device),
        and trigger warm-up once the first snapshot arrives.
        """
        device_id = snapshot_map.get("device_id")
        sampling_datetime: datetime | None = snapshot_map.get("sampling_datetime")

        if not device_id or not sampling_datetime:
            logger.warning(f"[LegacySender] Missing device_id or sampling_datetime in snapshot: {snapshot_map}")
            return

        # Ensure tz-aware (normalize to Asia/Taipei)
        if sampling_datetime.tzinfo is None:
            sampling_datetime = sampling_datetime.replace(tzinfo=TIMEZONE_INFO)
        else:
            sampling_datetime = sampling_datetime.astimezone(TIMEZONE_INFO)

        wstart = LegacySenderAdapter._window_start(sampling_datetime, int(self.send_interval_sec), tz=TIMEZONE_INFO)
        async with self._lock:
            self._latest_per_window[wstart][device_id] = {**snapshot_map, "sampling_datetime": sampling_datetime}

        if not self._first_snapshot_event.is_set():
            self._first_snapshot_event.set()

    async def start(self):
        """
        Start background tasks:
          - Create shared AsyncClient + Transport with full timeout config
          - _warmup_send_once(): wait first snapshot → send immediately
          - _scheduler_loop(): aligned periodic sending
          - _resend_worker_loop(): background resend
        """
        if self._client is None:
            timeout = httpx.Timeout(
                connect=5.0,  # TCP connection timeout
                read=10.0,  # Response read timeout
                write=5.0,  # Request write timeout
                pool=5.0,  # Connection pool timeout
            )
            self._client = httpx.AsyncClient(timeout=timeout)
            logger.info("[Sender] Shared HTTP client created (connect=5.0s, read=10.0s, write=5.0s, pool=5.0s)")

        if self._transport is None:
            self._transport = ResendTransport(self.ima_url, self._client, self._is_ok)

        # Keep task handles so stop() can cancel/await them.
        if self._warmup_task is None or self._warmup_task.done():
            self._warmup_task = asyncio.create_task(self._warmup_send_once())

        if self._scheduler_task is None or self._scheduler_task.done():
            self._scheduler_task = asyncio.create_task(self._scheduler_loop())

        # Start background resend worker (optional by config)
        if self.fail_resend_enabled:
            asyncio.create_task(self._delayed_resend_start())
            logger.info(
                f"[ResendWorker] scheduled to start after {self.resend_start_delay_sec}s "
                f"(interval={self.fail_resend_interval_sec}s, batch={self.fail_resend_batch}, "
                f"health_window={self.last_post_ok_within_sec}s)"
            )

    async def stop(self):
        """Graceful shutdown: stop tasks first, then close HTTP client."""
        self._stopping = True

        # 1) stop scheduler / warmup
        for tname, task in [("scheduler", self._scheduler_task), ("warmup", self._warmup_task)]:
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    logger.info(f"[Sender] {tname} task cancelled")
                except Exception as e:
                    logger.warning(f"[Sender] {tname} task stop error: {e}")

        # 2) stop resend worker
        try:
            self._resend_wakeup.set()
            if self._resend_task is not None and not self._resend_task.done():
                self._resend_task.cancel()
                try:
                    await self._resend_task
                except asyncio.CancelledError:
                    logger.info("[ResendWorker] cancelled")
                except Exception as e:
                    logger.warning(f"[Sender] resend worker stop error: {e}")
        except Exception as e:
            logger.warning(f"[Sender] Error stopping resend worker: {e}")

        # 3) close client
        try:
            if self._client is not None:
                await self._client.aclose()
                logger.info("[Sender] Shared HTTP client closed")
        except Exception as e:
            logger.warning(f"[Sender] Error closing HTTP client: {e}")

    # -------------------------
    # Internal
    # -------------------------

    async def _warmup_send_once(self, timeout_sec: int = 15, debounce_s: int = 1) -> None:
        """
        Perform an initial warm-up send after the first snapshot arrives.

        This sends a single full payload and persists it as ONE outbox file.
        """
        try:
            await asyncio.wait_for(self._first_snapshot_event.wait(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            logger.debug("Warm-up: no snapshot within timeout; skip immediate send.")
            return
        except asyncio.CancelledError:
            logger.info("[Warmup] cancelled")
            raise

        if debounce_s > 0:
            await asyncio.sleep(debounce_s)

        latest_by_device = await self._collect_latest_by_device_unlocked()

        all_items: list[dict] = []
        sent_candidates_sampling_datetime: dict[str, datetime] = {}
        label_now = datetime.now(TIMEZONE_INFO)

        for dev_id, snap in latest_by_device.items():
            last_label = self.__last_label_ts_by_device.get(dev_id, self._epoch)
            if label_now <= last_label:
                continue

            snap = self._apply_pt_ct_ratios(snap)

            snap_ts: datetime = snap["sampling_datetime"]
            age_sec = (label_now - snap_ts).total_seconds()
            is_stale = 1 if age_sec > self.fresh_window_sec else 0

            last_ts = self.__last_sent_ts_by_device.get(dev_id, self._epoch)
            if snap_ts <= last_ts:
                continue

            converted = convert_snapshot_to_legacy_payload(
                gateway_id=self.gateway_id,
                snapshot=snap,
                device_manager=self.device_manager,
            )

            if converted:
                age_ms = int(age_sec * 1000)
                for it in converted:
                    it.setdefault("Data", {})
                    it["Data"]["sampling_datetime"] = snap_ts.isoformat()
                    it["Data"]["report_ts"] = label_now.isoformat()
                    it["Data"]["sample_age_ms"] = age_ms
                    if is_stale:
                        it["Data"]["is_stale"] = 1
                        it["Data"]["stale_age_ms"] = age_ms

                all_items.extend(converted)
                sent_candidates_sampling_datetime[dev_id] = snap_ts

        # Add gateway heartbeat
        gw_item = await self._make_gw_heartbeat(label_now)
        all_items.append(gw_item)

        # ---- Build payload ONCE ----
        payload = self._store.wrap_items_as_payload(all_items, label_now)

        # ---- Persist ONE payload file ----
        outbox_file = await self._store.persist_payload(payload)

        logger.info(f"Warm-up send: {len(all_items)} items")

        ok = await self._post_with_retry(payload)
        if ok:
            self._store.delete(outbox_file)

            if sent_candidates_sampling_datetime:
                for dev_id in sent_candidates_sampling_datetime:
                    self.__last_label_ts_by_device[dev_id] = label_now
                self.__last_sent_ts_by_device.update(sent_candidates_sampling_datetime)
                await self._prune_buckets()

        self._first_send_done = True

    # -------------------------
    # Helpers
    # -------------------------
    def _apply_pt_ct_ratios(self, snap: dict) -> dict:
        """
        Calculate AverageVoltage and AverageCurrent from individual phase values.

        Important: DAE_PM210 meter internally applies PT/CT ratios to all register values.
        Therefore, we ONLY calculate averages WITHOUT additional ratio multiplication.
        """
        device_id: str = snap.get("device_id", "")
        device_model, slave_id = device_id.rsplit("_", 1)

        try:
            device = self.device_manager.get_device_by_model_and_slave_id(device_model, slave_id)
            if not device or device.model != "DAE_PM210":
                return snap
        except Exception:
            return snap

        values = snap.get("values")
        if not values or not isinstance(values, dict):
            logger.warning(f"[DAE_PM210] {device_id}: No 'values' dict found")
            return snap

        try:
            logger.debug(f"[DAE_PM210] {device_id}: Calculating averages (meter already applied PT/CT)")

            phase_v = [
                float(values.get("Phase_A_Voltage", 0) or 0),
                float(values.get("Phase_B_Voltage", 0) or 0),
                float(values.get("Phase_C_Voltage", 0) or 0),
            ]
            logger.debug(f"[DAE_PM210] {device_id}: Phase voltages: {phase_v}")

            if all(v == 0 for v in phase_v):
                phase_v = [
                    float(values.get("Line_AB_Voltage", 0) or 0),
                    float(values.get("Line_BC_Voltage", 0) or 0),
                    float(values.get("Line_CA_Voltage", 0) or 0),
                ]
                logger.debug(f"[DAE_PM210] {device_id}: Fallback to line voltages: {phase_v}")

            active_phase_count = sum(1 for v in phase_v if v != 0)
            if active_phase_count == 0:
                active_phase_count = 1

            logger.info(f"[DAE_PM210] {device_id}: Active phase count = {active_phase_count}")

            active_v = [v for v in phase_v if v != 0]
            if active_v:
                values["AverageVoltage"] = sum(active_v) / len(active_v)
                logger.debug(
                    f"[DAE_PM210] {device_id}: AverageVoltage = {values['AverageVoltage']:.2f}V "
                    f"(calculated from {len(active_v)} active phases)"
                )
            else:
                values["AverageVoltage"] = 0.0
                logger.warning(f"[DAE_PM210] {device_id}: All voltages are 0")

            i1 = float(values.get("Phase_A_Current", 0) or 0)
            i2 = float(values.get("Phase_B_Current", 0) or 0)
            i3 = float(values.get("Phase_C_Current", 0) or 0)

            logger.debug(f"[DAE_PM210] {device_id}: Phase currents: [{i1}, {i2}, {i3}]")

            values["AverageCurrent"] = (i1 + i2 + i3) / active_phase_count

            logger.debug(
                f"[DAE_PM210] {device_id}: AverageCurrent = {values['AverageCurrent']:.2f}A "
                f"(sum of all phases / {active_phase_count})"
            )

            logger.info(
                f"[DAE_PM210] {device_id}: Final - "
                f"Voltage={values.get('AverageVoltage', 0):.2f}V, "
                f"Current={values.get('AverageCurrent', 0):.2f}A"
            )

        except Exception as e:
            logger.error(f"[DAE_PM210] {device_id}: Calculation error: {e}", exc_info=True)

        return snap

    async def _collect_latest_by_device_unlocked(self) -> dict[str, dict]:
        """
        Compress all buckets → obtain a single "current latest" snapshot per device.
        """
        async with self._lock:
            latest_by_device: dict[str, dict] = {}
            for bucket in self._latest_per_window.values():
                for dev_id, snap in bucket.items():
                    prev = latest_by_device.get(dev_id)
                    if (not prev) or (snap["sampling_datetime"] > prev["sampling_datetime"]):
                        latest_by_device[dev_id] = snap
        return latest_by_device

    async def _prune_buckets(self) -> None:
        """
        Remove snapshots that were already sent or are older,
        to prevent buckets from growing indefinitely.
        """
        async with self._lock:
            for wstart in list(self._latest_per_window.keys()):
                bucket = self._latest_per_window[wstart]
                for dev_id in list(bucket.keys()):
                    snap_ts = bucket[dev_id]["sampling_datetime"]
                    last_ts = self.__last_sent_ts_by_device.get(dev_id, self._epoch)
                    if snap_ts <= last_ts:
                        bucket.pop(dev_id, None)
                if not bucket:
                    self._latest_per_window.pop(wstart, None)

    async def _post_with_retry(self, payload: dict) -> bool:
        """
        POST payload with retry logic and comprehensive error handling.

        Returns:
            True if successful, False otherwise
        """
        logger.debug(f"[POST] Starting at {datetime.now(TIMEZONE_INFO).strftime('%H:%M:%S')}")

        payload = self._normalize_missing_deep(payload)
        backoffs = [1, 2][: max(self.__attempt_count - 1, 0)]

        temp_client = None
        transport = self._transport
        if transport is None:
            timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
            temp_client = httpx.AsyncClient(timeout=timeout)
            transport = ResendTransport(self.ima_url, temp_client, self._is_ok)

        try:
            for i in range(self.__attempt_count):
                try:
                    logger.debug(f"[POST] Attempt {i+1}/{self.__attempt_count}")
                    ok, status, text = await transport.send(payload)

                    if ok:
                        logger.debug(f"[POST][Payload]: {payload}")
                        logger.info(f"[POST] ✓ Success: status={status}")
                        self.last_post_ok_at = datetime.now(TIMEZONE_INFO)
                        self._resend_wakeup.set()
                        return True

                    logger.warning(f"[POST] ✗ Failed: status={status}, preview={text[:200]!r}")

                except asyncio.CancelledError:
                    logger.info("[POST] cancelled")
                    raise
                except asyncio.TimeoutError:
                    logger.error(f"[POST] ✗ Attempt {i+1} TIMEOUT (asyncio.TimeoutError)")
                except httpx.ConnectTimeout as e:
                    logger.error(f"[POST] ✗ Attempt {i+1} CONNECT TIMEOUT: {e}")
                except httpx.ReadTimeout as e:
                    logger.error(f"[POST] ✗ Attempt {i+1} READ TIMEOUT: {e}")
                except httpx.WriteTimeout as e:
                    logger.error(f"[POST] ✗ Attempt {i+1} WRITE TIMEOUT: {e}")
                except httpx.PoolTimeout as e:
                    logger.error(f"[POST] ✗ Attempt {i+1} POOL TIMEOUT: {e}")
                except httpx.TimeoutException as e:
                    logger.error(f"[POST] ✗ Attempt {i+1} TIMEOUT (httpx): {e}")
                except httpx.ConnectError as e:
                    logger.error(f"[POST] ✗ Attempt {i+1} CONNECT ERROR: {e}")
                except httpx.NetworkError as e:
                    logger.error(f"[POST] ✗ Attempt {i+1} NETWORK ERROR: {e}")
                except Exception as e:
                    logger.exception(f"[POST] ✗ Attempt {i+1} UNEXPECTED ERROR: {e}")

                if i < len(backoffs):
                    await asyncio.sleep(backoffs[i])

            logger.warning(f"[POST] ✗ All {self.__attempt_count} attempts exhausted")

        finally:
            if temp_client is not None:
                try:
                    await temp_client.aclose()
                except Exception:
                    pass

        await asyncio.to_thread(self._store.enforce_budget)
        return False

    @staticmethod
    def _window_start(ts: datetime, interval_sec: int, tz: ZoneInfo = TIMEZONE_INFO) -> datetime:
        """
        Align `sampling_datetime` to tumbling window start by epoch-based alignment.
        This is ONLY for internal cache bucket key (does not affect sending timestamp).
        """
        interval = int(interval_sec)
        if interval <= 0:
            interval = 1

        ts_tz = ts.astimezone(tz) if ts.tzinfo else ts.replace(tzinfo=tz)
        ts_tz = ts_tz.replace(microsecond=0)

        epoch = datetime(1970, 1, 1, tzinfo=tz)
        elapsed = int((ts_tz - epoch).total_seconds())
        aligned_elapsed = (elapsed // interval) * interval
        return epoch + timedelta(seconds=aligned_elapsed)

    @staticmethod
    def _resolve_gateway_id(config_gateway_id: str) -> str:
        hostname: str = socket.gethostname()

        if len(hostname) == 11:
            if hostname == "99999999999":
                gateway_id = config_gateway_id[:11]
                logger.info(f"[GatewayID] Using config gateway_id={gateway_id} (hostname is default {hostname})")
                return gateway_id

            logger.info(f"[GatewayID] Using hostname gateway_id={hostname}")
            return hostname

        gateway_id: str = config_gateway_id[:11]
        logger.info(f"[GatewayID] Using config gateway_id={gateway_id} (hostname not 11 chars)")
        return gateway_id

    @staticmethod
    def _normalize_missing_value(v):
        if isinstance(v, (int, float)) and v == -1:
            return -1
        return v

    @staticmethod
    def _normalize_missing_deep(obj):
        if isinstance(obj, dict):
            return {
                k: LegacySenderAdapter._normalize_missing_deep(LegacySenderAdapter._normalize_missing_value(v))
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [LegacySenderAdapter._normalize_missing_deep(x) for x in obj]
        return LegacySenderAdapter._normalize_missing_value(obj)

    @staticmethod
    def _is_ok(resp: httpx.Response) -> bool:
        return (resp is not None) and (resp.status_code == 200) and ("00000" in (resp.text or ""))

    async def _scheduler_loop(self):
        """
        Main scheduler loop with timeout protection.

        IMPORTANT:
        - Total timeout here should NOT cancel the underlying send, to avoid outbox half-state.
        - Use shield(send_task) so scheduler can move on, while send continues safely.
        """
        logger.info(
            f"Scheduler: anchor={self.anchor_offset_sec}s, interval={self.send_interval_sec}s, "
            f"fail_resend_enabled={self.fail_resend_enabled}, fail_resend_interval_sec={self.fail_resend_interval_sec}, "
            f"fail_resend_batch={self.fail_resend_batch}, last_post_ok_within_sec={self.last_post_ok_within_sec}"
        )

        next_label = self._compute_next_label_time(datetime.now(TIMEZONE_INFO))

        try:
            while not self._stopping:
                now = datetime.now(TIMEZONE_INFO)
                logger.debug(
                    f"[Scheduler] Cycle start: now={now.strftime('%H:%M:%S')}, "
                    f"next_label={next_label.strftime('%H:%M:%S')}"
                )

                wait_sec = (next_label - now).total_seconds()
                if wait_sec > 0:
                    await asyncio.sleep(wait_sec)

                if self._stopping:
                    break

                if self.tick_grace_sec > 0:
                    await asyncio.sleep(self.tick_grace_sec)

                if self._stopping:
                    break

                logger.info(f"[Scheduler] Starting send at {next_label.strftime('%H:%M:%S')}")

                send_task = asyncio.create_task(self._send_at_label_time(next_label))
                try:
                    await asyncio.wait_for(asyncio.shield(send_task), timeout=30.0)
                    logger.info(f"[Scheduler] Send completed at {datetime.now(TIMEZONE_INFO).strftime('%H:%M:%S')}")
                except asyncio.TimeoutError:
                    logger.error(
                        f"[Scheduler] SEND TIMEOUT at {next_label.strftime('%H:%M:%S')} "
                        f"(exceeded 30s wait) - send continues in background"
                    )
                except asyncio.CancelledError:
                    logger.info("[Scheduler] cancelled")
                    raise
                except Exception as e:
                    logger.error(
                        f"[Scheduler] Unexpected error at {next_label.strftime('%H:%M:%S')}: {e}", exc_info=True
                    )

                next_label = next_label + timedelta(seconds=self.send_interval_sec)

        except asyncio.CancelledError:
            logger.info("[Scheduler] cancelled")
            raise
        except Exception as e:
            logger.error(f"[Scheduler] crashed: {e}", exc_info=True)

    def _compute_next_label_time(self, now: datetime) -> datetime:
        base_datatime = now.replace(microsecond=0)
        anchor = int(self.anchor_offset_sec)
        candidate = base_datatime.replace(second=anchor)
        interval = float(self.send_interval_sec)

        while candidate <= now:
            candidate += timedelta(seconds=interval)
        return candidate

    async def _send_at_label_time(self, label_time: datetime) -> None:
        """
        Scheduled send at a fixed label timestamp.

        All legacy items from this tick are persisted as ONE payload file.
        """
        latest_by_device = await self._collect_latest_by_device_unlocked()

        all_items: list[dict] = []
        sent_candidates_ts: dict[str, datetime] = {}
        visible_deadline = label_time + timedelta(seconds=self.tick_grace_sec)

        for dev_id, snap in latest_by_device.items():
            snap_ts: datetime = snap["sampling_datetime"]
            if snap_ts > visible_deadline:
                continue

            age_sec = (label_time - snap_ts).total_seconds()
            is_stale = 1 if age_sec > self.fresh_window_sec else 0

            last_label = self.__last_label_ts_by_device.get(dev_id, self._epoch)
            if label_time <= last_label:
                continue

            snap = self._apply_pt_ct_ratios(snap)

            converted = convert_snapshot_to_legacy_payload(
                gateway_id=self.gateway_id,
                snapshot=snap,
                device_manager=self.device_manager,
            )

            if converted:
                age_ms = int(age_sec * 1000)
                for it in converted:
                    it.setdefault("Data", {})
                    it["Data"]["sampling_datetime"] = snap_ts.isoformat()
                    it["Data"]["report_ts"] = label_time.isoformat()
                    it["Data"]["sample_age_ms"] = age_ms
                    if is_stale:
                        it["Data"]["is_stale"] = 1
                        it["Data"]["stale_age_ms"] = age_ms

                all_items.extend(converted)
                sent_candidates_ts[dev_id] = snap_ts

        gw_item = await self._make_gw_heartbeat(label_time)
        all_items.append(gw_item)

        payload = self._store.wrap_items_as_payload(all_items, label_time)
        outbox_file = await self._store.persist_payload(payload)

        logger.debug(f"Scheduled send: {len(all_items)} items")

        ok = await self._post_with_retry(payload)
        if ok:
            self._store.delete(outbox_file)

            if sent_candidates_ts:
                for dev_id in sent_candidates_ts:
                    self.__last_label_ts_by_device[dev_id] = label_time
                self.__last_sent_ts_by_device.update(sent_candidates_ts)
                await self._prune_buckets()

    async def _make_gw_heartbeat(self, report_datetime: datetime) -> dict:
        cpu_temp_task = asyncio.create_task(self._system_info.get_cpu_temperature())
        cpu_temp: float = await cpu_temp_task
        ssh_port: int = self._get_reverse_ssh_port()

        return {
            "DeviceID": f"{self.gateway_id}_{self.series_number}00{EquipmentType.GW}",
            "Data": {
                "HB": 1,
                "report_ts": report_datetime.isoformat(),
                "SSHPort": ssh_port,
                "WebBulbOffset": cpu_temp,
                "Status": self._system_info.get_reboot_count(),
            },
        }

    # ---------- Background resend worker ----------

    async def _resend_worker_loop(self) -> None:
        """
        Background resend loop with time alignment.
        """
        try:
            while not self._stopping:
                now = datetime.now(TIMEZONE_INFO)
                next_run = self._compute_next_resend_time(now)
                wait_sec = (next_run - now).total_seconds()

                logger.debug(f"[ResendWorker] next run at {next_run.strftime('%H:%M:%S')}, waiting {wait_sec:.1f}s")

                try:
                    await asyncio.wait_for(self._resend_wakeup.wait(), timeout=wait_sec)
                    logger.debug("[ResendWorker] woken up early by success signal")
                except asyncio.TimeoutError:
                    pass
                finally:
                    self._resend_wakeup.clear()

                if self._stopping:
                    break

                now = datetime.now(TIMEZONE_INFO)
                if self.last_post_ok_within_sec > 0:
                    if self.last_post_ok_at is None:
                        logger.info("[ResendWorker] skip: no successful POST yet")
                        continue

                    elapsed_time = (now - self.last_post_ok_at).total_seconds()
                    if elapsed_time > self.last_post_ok_within_sec:
                        logger.info(
                            f"[ResendWorker] skip: no recent success within "
                            f"{self.last_post_ok_within_sec}s "
                            f"(last_ok={self.last_post_ok_at.strftime('%H:%M:%S')}, "
                            f"elapsed={elapsed_time:.1f}s)"
                        )
                        continue

                try:
                    processed, success = await self._resend_process_batch(self.fail_resend_batch)

                    if processed == 0:
                        logger.debug("[ResendWorker] no files to process")
                        continue

                    logger.info(f"[ResendWorker] processed {processed} files, succeeded {success}")

                    if success > 0:
                        self._resend_wakeup.set()

                except Exception as e:
                    logger.warning(f"[ResendWorker] batch error: {e}")

        except asyncio.CancelledError:
            logger.info("[ResendWorker] cancelled")
            raise
        except Exception as e:
            logger.error(f"[ResendWorker] crashed: {e}", exc_info=True)

    def _parse_iso_timestamp(self, timestamp_str: str | None) -> datetime | None:
        if not timestamp_str:
            return None
        try:
            dt: datetime = datetime.fromisoformat(timestamp_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TIMEZONE_INFO)
            else:
                dt = dt.astimezone(TIMEZONE_INFO)
            return dt
        except Exception:
            return None

    def _ts_from_filename(self, filename: str) -> datetime | None:
        match = re.match(r"resend_(\d{14})_", filename)
        if not match:
            return None
        try:
            base_datetime = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
            return base_datetime.replace(tzinfo=TIMEZONE_INFO)
        except Exception:
            return None

    async def _resend_process_batch(self, batch: int) -> tuple[int, int]:
        files: list[str] = await asyncio.to_thread(self._store.pick_batch, batch, min_age_sec=0.0)
        if not files:
            return 0, 0

        temp_client: httpx.AsyncClient | None = None
        transport = self._transport
        if transport is None:
            timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
            temp_client = httpx.AsyncClient(timeout=timeout)
            transport = ResendTransport(self.ima_url, temp_client, self._is_ok)

        processed = 0
        deleted_total = 0

        full_packets: list[tuple[str, dict]] = []
        item_groups: dict[str, dict] = {}

        for file_path in files:
            file_name = os.path.basename(file_path)
            try:
                async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                    raw = await f.read()
            except FileNotFoundError:
                logger.info(f"[ResendWorker] skipped, already gone: {file_name}")
                processed += 1
                continue
            except Exception as e:
                logger.warning(f"[ResendWorker] read failed for {file_name}: {e}")
                _, failed = self._store.retry_or_fail(file_path, max_retry=self.__max_retry)
                if failed:
                    logger.warning(f"[ResendWorker] marked .fail: {file_name}")
                processed += 1
                continue

            json_obj = None
            try:
                json_obj = json.loads(raw)
            except Exception:
                json_obj = None

            if isinstance(json_obj, dict) and "FUNC" in json_obj:
                full_packets.append((file_path, json_obj))
            elif isinstance(json_obj, dict) and "DeviceID" in json_obj:
                report_timestamp: str = (json_obj.get("Data") or {}).get("report_ts")
                ts_dt = (
                    self._parse_iso_timestamp(report_timestamp)
                    or self._ts_from_filename(file_name)
                    or datetime.now(TIMEZONE_INFO)
                )
                ts_key = ts_dt.strftime("%Y%m%d%H%M%S")
                item_group: dict = item_groups.setdefault(ts_key, {"ts": ts_dt, "items": [], "paths": []})
                item_group["items"].append(json_obj)
                item_group["paths"].append(file_path)
            else:
                ts_dt: datetime = self._ts_from_filename(file_name) or datetime.now(TIMEZONE_INFO)
                ts_key: str = f"RAW-{ts_dt.strftime('%Y%m%d%H%M%S')}#{file_name}"
                item_groups.setdefault(ts_key, {"ts": ts_dt, "items": [], "paths": []})
                item_groups[ts_key]["items"].append(json_obj if isinstance(json_obj, dict) else {"_raw": raw})
                item_groups[ts_key]["paths"].append(file_path)

            processed += 1

        for file_path, packet in full_packets:
            file_name = os.path.basename(file_path)
            try:
                ok, status, text = await transport.send(packet)
                logger.info(f"[ResendWorker] (packet) {file_name}, resp: {status} {text[:120]!r}")
                if ok:
                    self._store.delete(file_path)
                    self.last_post_ok_at = datetime.now(TIMEZONE_INFO)
                    deleted_total += 1
                    logger.info(f"[ResendWorker] success, deleted: {file_name}")
                else:
                    _, failed = self._store.retry_or_fail(file_path, max_retry=self.__max_retry)
                    if failed:
                        logger.warning(f"[ResendWorker] marked .fail: {file_name}")
            except asyncio.CancelledError:
                logger.info("[ResendWorker] cancelled during packet send")
                raise
            except Exception as e:
                logger.warning(f"[ResendWorker] failed (packet) for {file_name}: {e}")
                _, failed = self._store.retry_or_fail(file_path, max_retry=self.__max_retry)
                if failed:
                    logger.warning(f"[ResendWorker] marked .fail: {file_name}")

        for ts_key, item_group in sorted(item_groups.items(), key=lambda kv: kv[1]["ts"]):
            ts_dt = item_group["ts"]
            items = []
            for it in item_group["items"]:
                if isinstance(it, dict) and "DeviceID" in it:
                    items.append(it)

            if not items:
                continue

            payload = self._store.wrap_items_as_payload(items, ts_dt)
            logger.debug(f"[ResendWorker] Sending group ts={ts_key} with {len(items)} items")
            file_paths = item_group["paths"]

            try:
                ok, status, text = await transport.send(payload)
                logger.info(f"[ResendWorker] (group ts={ts_key}) resp: {status} {text[:120]!r}")
                if ok:
                    for p in file_paths:
                        self._store.delete(p)
                        deleted_total += 1
                    self.last_post_ok_at = datetime.now(TIMEZONE_INFO)
                    logger.info(f"[ResendWorker] success, deleted group of {len(file_paths)} file(s) for ts={ts_key}")
                else:
                    for p in file_paths:
                        _, failed = self._store.retry_or_fail(p, max_retry=self.__max_retry)
                        if failed:
                            logger.warning(f"[ResendWorker] marked .fail: {os.path.basename(p)}")
            except asyncio.CancelledError:
                logger.info("[ResendWorker] cancelled during group send")
                raise
            except Exception as e:
                logger.warning(f"[ResendWorker] failed (group ts={ts_key}): {e}")
                for p in file_paths:
                    _, failed = self._store.retry_or_fail(p, max_retry=self.__max_retry)
                    if failed:
                        logger.warning(f"[ResendWorker] marked .fail: {os.path.basename(p)}")

        if temp_client is not None:
            try:
                await temp_client.aclose()
            except Exception:
                pass

        await asyncio.to_thread(self._store.enforce_budget)
        return processed, deleted_total

    async def _delayed_resend_start(self):
        """
        Delayed start for Resend Worker, aligned to the configured anchor offset.
        """
        now = datetime.now(TIMEZONE_INFO)
        min_start_time = now + timedelta(seconds=self.resend_start_delay_sec)
        next_aligned = self._compute_next_resend_time(min_start_time)
        wait_sec = (next_aligned - now).total_seconds()

        logger.info(
            f"[ResendWorker] scheduled start at {next_aligned.strftime('%Y-%m-%d %H:%M:%S')} "
            f"(anchor={self.resend_anchor_offset_sec}s, "
            f"interval={self.fail_resend_interval_sec}s, "
            f"min_delay={self.resend_start_delay_sec}s, "
            f"waiting {wait_sec:.1f}s)"
        )

        await asyncio.sleep(wait_sec)

        if self._stopping:
            logger.info("[ResendWorker] start aborted: stopping=True")
            return

        logger.info(f"[ResendWorker] starting now at {datetime.now(TIMEZONE_INFO).strftime('%H:%M:%S')}")
        self._resend_task = asyncio.create_task(self._resend_worker_loop())

    def _compute_next_resend_time(self, after: datetime) -> datetime:
        interval = self.fail_resend_interval_sec
        anchor = self.resend_anchor_offset_sec

        epoch = datetime(1970, 1, 1, tzinfo=TIMEZONE_INFO)
        after_tz = after.astimezone(TIMEZONE_INFO) if after.tzinfo else after.replace(tzinfo=TIMEZONE_INFO)

        elapsed_sec = int((after_tz - epoch).total_seconds())
        cycle = (elapsed_sec - anchor) // interval
        next_aligned_sec = (cycle + 1) * interval + anchor
        next_aligned = epoch + timedelta(seconds=next_aligned_sec)

        while next_aligned <= after_tz:
            next_aligned += timedelta(seconds=interval)

        return next_aligned

    def _get_reverse_ssh_port(self) -> int:
        try:
            remote_access_config: RemoteAccessConfig = self._system_config.REMOTE_ACCESS
            reverse_ssh: ReverseSshConfig = remote_access_config.REVERSE_SSH

            if reverse_ssh.PORT_SOURCE == "config":
                if isinstance(reverse_ssh.PORT, int):
                    return reverse_ssh.PORT
                logger.warning("[LegacySender] REVERSE_SSH.PORT invalid or missing")
                return 22

            logger.info("[LegacySender] REVERSE_SSH.PORT_SOURCE=mqtt (not implemented)")
            return 0

        except Exception as e:
            logger.warning(f"[LegacySender] resolve reverse ssh port failed: {e}")
            return 0
