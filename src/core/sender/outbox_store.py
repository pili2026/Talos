import json
import os
import re
from datetime import datetime
from typing import List, Tuple
from zoneinfo import ZoneInfo

import aiofiles

from core.sender.legacy.resend_file_util import extract_retry_count, increment_retry_name, mark_as_fail


class OutboxStore:
    """
    Encapsulates access and management for the outbox:
      - persist a single item
      - wrap items into a PushIMAData payload
      - batch selection (retryN first, FIFO)
      - delete / increment retry / mark as fail
      - storage protection (can be disabled)
    """

    def __init__(
        self,
        dirpath: str,
        tz: ZoneInfo,
        *,
        gateway_id: str,
        resend_quota_mb: int,
        fs_free_min_mb: int,
        protect_recent_sec: float,
        cleanup_batch: int,
        cleanup_enabled: bool,
    ):
        self.dir = dirpath
        self.tz = tz
        self.gateway_id = gateway_id

        self.resend_quota_mb = resend_quota_mb
        self.fs_free_min_mb = fs_free_min_mb
        self.protect_recent_sec = float(protect_recent_sec)
        self.cleanup_batch = int(cleanup_batch)
        self.cleanup_enabled = bool(cleanup_enabled)

        os.makedirs(self.dir, exist_ok=True)

    # ---------- persist / wrap ----------

    async def persist_item(self, item: dict) -> str:
        """Persist a SINGLE Data item (with DeviceID/Data) to the outbox and return the absolute path."""
        now = datetime.now(self.tz)
        base = now.strftime("%Y%m%d%H%M%S")
        ms = f"{int(now.microsecond/1000):03d}"
        suffix = os.urandom(2).hex()
        fp = os.path.join(self.dir, f"resend_{base}_{ms}_{suffix}.json")
        async with aiofiles.open(fp, "w", encoding="utf-8") as f:
            await f.write(json.dumps(item, ensure_ascii=False))
        return fp

    async def persist_payload(self, payload: dict) -> str:
        """
        Persist a FULL PushIMAData payload as a single outbox file.

        This guarantees "save first, upload later" semantics and reduces
        disk I/O from O(items) to O(1) per scheduler tick.
        """
        now = datetime.now(self.tz)
        base = now.strftime("%Y%m%d%H%M%S")
        ms = f"{int(now.microsecond / 1000):03d}"
        suffix = os.urandom(2).hex()

        fp = os.path.join(self.dir, f"resend_{base}_{ms}_{suffix}.json")

        async with aiofiles.open(fp, "w", encoding="utf-8") as f:
            await f.write(json.dumps(payload, ensure_ascii=False))

        return fp

    async def persist_batch(self, items: list[dict], label_ts: datetime) -> str:
        """
        Persist a batch of legacy items as a FULL PushIMAData payload.

        This is a thin wrapper around persist_payload().
        """
        payload = self.wrap_items_as_payload(items, label_ts)
        return await self.persist_payload(payload)

    def wrap_items_as_payload(self, items: list[dict], ts: datetime) -> dict:
        return {
            "FUNC": "PushIMAData",
            "version": "6.0",
            "GatewayID": self.gateway_id,
            "Timestamp": ts.strftime("%Y%m%d%H%M%S"),
            "Data": items,
        }

    # ---------- pick / mutate ----------

    def pick_batch(self, limit: int, *, min_age_sec: float = 0.0) -> List[str]:
        """Pick up to `limit` files. retryN first, then fresh .json; both FIFO by mtime."""
        try:
            entries = os.listdir(self.dir)
        except FileNotFoundError:
            return []

        retry_files, fresh_files = [], []
        for fn in entries:
            if re.search(r"\.retry\d+\.json$", fn):
                retry_files.append(fn)
            elif fn.endswith(".json"):
                fresh_files.append(fn)

        now = datetime.now(self.tz).timestamp()

        def eligible(fn: str) -> bool:
            fp = os.path.join(self.dir, fn)
            try:
                return (now - os.path.getmtime(fp)) >= float(min_age_sec)
            except OSError:
                return False

        retry_files = [f for f in retry_files if eligible(f)]
        fresh_files = [f for f in fresh_files if eligible(f)]

        def mtime_key(fn: str) -> float:
            try:
                return os.path.getmtime(os.path.join(self.dir, fn))
            except OSError:
                return float("inf")

        retry_files.sort(key=mtime_key)
        fresh_files.sort(key=mtime_key)

        selected = (retry_files + fresh_files)[: max(0, int(limit))]
        return [os.path.join(self.dir, fn) for fn in selected]

    def delete(self, path: str) -> None:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

    def retry_or_fail(self, path: str, *, max_retry: int) -> Tuple[str | None, bool]:
        """
        Increment retry or mark as fail:
          - max_retry < 0 → always increment retry (unlimited retries)
          - otherwise, if retry count reaches the limit → mark as fail
        return: (new_path_if_renamed, failed_marked_bool)
        """
        fn = os.path.basename(path)
        retry_count = extract_retry_count(fn)

        # Unlimited retries
        if max_retry < 0:
            new_name = increment_retry_name(fn)
            new_path = os.path.join(self.dir, new_name)
            try:
                os.rename(path, new_path)
            except FileNotFoundError:
                return None, False
            return new_path, False

        # With an upper bound
        if retry_count + 1 >= max_retry:
            try:
                mark_as_fail(path)
            except FileNotFoundError:
                pass
            return None, True

        new_name = increment_retry_name(fn)
        new_path = os.path.join(self.dir, new_name)
        try:
            os.rename(path, new_path)
        except FileNotFoundError:
            return None, False
        return new_path, False

    # ---------- storage budget ----------

    def enforce_budget(self) -> None:
        if not self.cleanup_enabled:
            return
        try:
            if not (
                self._dir_size_mb(self.dir) > self.resend_quota_mb or self._fs_free_mb(self.dir) < self.fs_free_min_mb
            ):
                return

            files = []
            now_ts = datetime.now(self.tz).timestamp()
            for fn in os.listdir(self.dir):
                if not (fn.endswith(".json") or re.search(r"\.retry\d+\.json$", fn) or fn.endswith(".fail")):
                    continue
                fp = os.path.join(self.dir, fn)
                try:
                    age = now_ts - os.path.getmtime(fp)
                except OSError:
                    continue
                files.append((age, fn))

            files.sort(reverse=True)  # Delete older ones first
            deleted = 0

            def eligible(age: float) -> bool:
                return age >= self.protect_recent_sec

            # Delete non-.fail first
            for age, fn in list(files):
                if deleted >= self.cleanup_batch:
                    break
                if not eligible(age) or fn.endswith(".fail"):
                    continue
                try:
                    os.remove(os.path.join(self.dir, fn))
                    deleted += 1
                except OSError:
                    pass

            # Then delete .fail
            if deleted < self.cleanup_batch:
                for age, fn in list(files):
                    if deleted >= self.cleanup_batch:
                        break
                    if not eligible(age) or not fn.endswith(".fail"):
                        continue
                    try:
                        os.remove(os.path.join(self.dir, fn))
                        deleted += 1
                    except OSError:
                        pass
        except Exception:
            # Fail silently; do not block the main flow
            pass

    # ---------- helpers ----------

    @staticmethod
    def _dir_size_mb(path: str) -> float:
        total = 0
        for root, _, files in os.walk(path):
            for fn in files:
                fp = os.path.join(root, fn)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
        return total / (1024 * 1024)

    @staticmethod
    def _fs_free_mb(path: str) -> float:
        st = os.statvfs(path)
        return (st.f_bavail * st.f_frsize) / (1024 * 1024)
