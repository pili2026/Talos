import os
from datetime import datetime

import pytest

from core.sender.outbox_store import OutboxStore
from core.util.time_util import TIMEZONE_INFO


@pytest.fixture
def outbox_store(tmp_path):
    """Create outbox store with test directory"""
    store = OutboxStore(
        dirpath=str(tmp_path / "outbox"),
        tz=TIMEZONE_INFO,
        gateway_id="test_gw",
        resend_quota_mb=256,
        fs_free_min_mb=512,
        protect_recent_sec=300,
        cleanup_batch=100,
        cleanup_enabled=False,
    )
    return store


class TestOutboxStorePersist:
    """Test item persistence"""

    @pytest.mark.asyncio
    async def test_when_persist_item_then_creates_file(self, outbox_store):
        """Test that persist_item creates a file"""
        # Arrange
        item = {"DeviceID": "test_001", "Data": {"value": 123}}

        # Act
        filepath = await outbox_store.persist_item(item)

        # Assert
        assert os.path.exists(filepath)
        assert filepath.endswith(".json")

    @pytest.mark.asyncio
    async def test_when_persist_item_then_file_contains_data(self, outbox_store):
        """Test that persisted file contains correct data"""
        # Arrange
        item = {"DeviceID": "test_001", "Data": {"value": 123}}

        # Act
        filepath = await outbox_store.persist_item(item)

        # Assert
        import json

        with open(filepath, "r") as f:
            loaded = json.load(f)
        assert loaded == item


class TestOutboxStorePickBatch:
    """Test batch file selection"""

    @pytest.mark.asyncio
    async def test_when_pick_batch_then_prefers_retry_files(self, outbox_store, tmp_path):
        """Test that retry files are picked before fresh files"""
        # Arrange
        outbox_dir = tmp_path / "outbox"
        outbox_dir.mkdir(parents=True, exist_ok=True)

        # Create files with different retry counts
        fresh_file = outbox_dir / "resend_20250101120000_000_aaa.json"
        retry1_file = outbox_dir / "resend_20250101120001_000_bbb.retry1.json"
        retry2_file = outbox_dir / "resend_20250101120002_000_ccc.retry2.json"

        fresh_file.write_text('{"test": "fresh"}')
        retry1_file.write_text('{"test": "retry1"}')
        retry2_file.write_text('{"test": "retry2"}')

        # Act
        files = outbox_store.pick_batch(10)

        # Assert
        filenames = [os.path.basename(f) for f in files]
        # All retry files should come before fresh
        retry_count = sum(1 for f in filenames if ".retry" in f)
        assert retry_count == 2
        # First files should be retry files
        assert ".retry" in filenames[0]
        assert ".retry" in filenames[1]

    @pytest.mark.asyncio
    async def test_when_pick_batch_then_uses_fifo_order(self, outbox_store, tmp_path):
        """Test that files are picked in FIFO order (oldest first)"""
        # Arrange
        import time

        outbox_dir = tmp_path / "outbox"
        outbox_dir.mkdir(parents=True, exist_ok=True)

        file1 = outbox_dir / "resend_20250101120000_000_aaa.json"
        file1.write_text('{"test": 1}')
        time.sleep(0.01)

        file2 = outbox_dir / "resend_20250101120001_000_bbb.json"
        file2.write_text('{"test": 2}')
        time.sleep(0.01)

        file3 = outbox_dir / "resend_20250101120002_000_ccc.json"
        file3.write_text('{"test": 3}')

        # Act
        files = outbox_store.pick_batch(10)

        # Assert (oldest mtime first)
        assert os.path.basename(files[0]).endswith("aaa.json")
        assert os.path.basename(files[1]).endswith("bbb.json")
        assert os.path.basename(files[2]).endswith("ccc.json")


class TestOutboxStoreRetryOrFail:
    """Test retry/fail file naming"""

    def test_when_retry_or_fail_under_limit_then_increments_retry(self, outbox_store, tmp_path):
        """Test that file is renamed to next retry number"""
        # Arrange
        outbox_dir = tmp_path / "outbox"
        outbox_dir.mkdir(parents=True, exist_ok=True)

        original_file = outbox_dir / "resend_20250101120000_000_test.json"
        original_file.write_text('{"test": 1}')

        # Act
        new_path, failed = outbox_store.retry_or_fail(str(original_file), max_retry=3)

        # Assert
        assert failed is False
        assert new_path is not None
        assert ".retry1.json" in new_path
        assert os.path.exists(new_path)
        assert not os.path.exists(original_file)

    def test_when_retry_or_fail_at_limit_then_marks_fail(self, outbox_store, tmp_path):
        """Test that file is marked as .fail at retry limit"""
        # Arrange
        outbox_dir = tmp_path / "outbox"
        outbox_dir.mkdir(parents=True, exist_ok=True)

        retry_file = outbox_dir / "resend_20250101120000_000_test.retry2.json"
        retry_file.write_text('{"test": 1}')

        # Act
        new_path, failed = outbox_store.retry_or_fail(str(retry_file), max_retry=3)

        # Assert
        assert failed is True
        assert new_path is None
        fail_file = outbox_dir / "resend_20250101120000_000_test.fail"
        assert fail_file.exists()

    def test_when_retry_or_fail_unlimited_then_never_fails(self, outbox_store, tmp_path):
        """Test that unlimited retry never creates .fail files"""
        # Arrange
        outbox_dir = tmp_path / "outbox"
        outbox_dir.mkdir(parents=True, exist_ok=True)

        retry_file = outbox_dir / "resend_20250101120000_000_test.retry99.json"
        retry_file.write_text('{"test": 1}')

        # Act
        new_path, failed = outbox_store.retry_or_fail(str(retry_file), max_retry=-1)

        # Assert
        assert failed is False
        assert ".retry100.json" in new_path


class TestOutboxStoreWrapPayload:
    """Test payload wrapping"""

    def test_when_wrap_items_then_creates_valid_payload(self, outbox_store):
        """Test that wrap creates valid PushIMAData payload"""
        # Arrange
        items = [{"DeviceID": "test_001", "Data": {"value": 1}}, {"DeviceID": "test_002", "Data": {"value": 2}}]
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=TIMEZONE_INFO)

        # Act
        payload = outbox_store.wrap_items_as_payload(items, ts)

        # Assert
        assert payload["FUNC"] == "PushIMAData"
        assert payload["version"] == "6.0"
        assert payload["GatewayID"] == "test_gw"
        assert payload["Timestamp"] == "20250101120000"
        assert len(payload["Data"]) == 2
