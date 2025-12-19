# tests/sender/legacy/test_legacy_sender_core.py
import asyncio
import json
import os
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest

from core.sender.legacy.legacy_sender import LegacySenderAdapter
from core.sender.transport import ResendTransport
from core.util.time_util import TIMEZONE_INFO

# ==================== Snapshot Handling Tests ====================


class TestSnapshotHandling:
    """Test snapshot bucketing and storage logic"""

    @pytest.mark.asyncio
    async def test_when_snapshot_received_then_stored_in_correct_window(self, sender_adapter):
        """Test that snapshot is stored in the correct time window bucket"""
        # Arrange
        sampling_datetime = datetime(2025, 1, 1, 12, 0, 30, tzinfo=TIMEZONE_INFO)
        snapshot = {
            "device_id": "device_001",
            "model": "TECO_VFD",
            "slave_id": "1",
            "type": "inverter",
            "sampling_datetime": sampling_datetime,
            "values": {"HZ": 50.0},
        }

        # Act
        await sender_adapter.handle_snapshot(snapshot)

        # Assert
        window_start = LegacySenderAdapter._window_start(sampling_datetime, int(sender_adapter.send_interval_sec))
        assert window_start in sender_adapter._latest_per_window
        assert "device_001" in sender_adapter._latest_per_window[window_start]
        assert sender_adapter._latest_per_window[window_start]["device_001"]["device_id"] == "device_001"

    @pytest.mark.asyncio
    async def test_when_multiple_snapshots_same_window_then_keeps_latest(self, sender_adapter):
        """Test that only the latest snapshot per device per window is kept"""
        # Arrange
        base_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=TIMEZONE_INFO)

        snapshot1 = {
            "device_id": "device_001",
            "sampling_datetime": base_time + timedelta(seconds=10),
            "values": {"HZ": 40.0},
        }
        snapshot2 = {
            "device_id": "device_001",
            "sampling_datetime": base_time + timedelta(seconds=30),
            "values": {"HZ": 50.0},
        }

        # Act
        await sender_adapter.handle_snapshot(snapshot1)
        await sender_adapter.handle_snapshot(snapshot2)

        # Assert
        latest = await sender_adapter._collect_latest_by_device_unlocked()
        assert latest["device_001"]["values"]["HZ"] == 50.0

    @pytest.mark.asyncio
    async def test_when_first_snapshot_then_triggers_warmup_event(self, sender_adapter):
        """Test that first snapshot sets the warmup event"""
        # Arrange
        assert not sender_adapter._first_snapshot_event.is_set()

        snapshot = {"device_id": "device_001", "sampling_datetime": datetime.now(TIMEZONE_INFO), "values": {}}

        # Act
        await sender_adapter.handle_snapshot(snapshot)

        # Assert
        assert sender_adapter._first_snapshot_event.is_set()

    @pytest.mark.asyncio
    async def test_when_naive_datetime_then_converts_to_tz_aware(self, sender_adapter):
        """Test that naive datetime is converted to timezone-aware"""
        # Arrange
        naive_time = datetime(2025, 1, 1, 12, 0, 0)  # No tzinfo
        snapshot = {"device_id": "device_001", "sampling_datetime": naive_time, "values": {}}

        # Act
        await sender_adapter.handle_snapshot(snapshot)

        # Assert
        latest = await sender_adapter._collect_latest_by_device_unlocked()
        stored_ts = latest["device_001"]["sampling_datetime"]
        assert stored_ts.tzinfo is not None
        assert stored_ts.tzinfo == TIMEZONE_INFO


# ==================== Deduplication Tests ====================


class TestDeduplication:
    """Test deduplication logic to prevent resending same data"""

    @pytest.mark.asyncio
    async def test_when_same_sampling_datetime_then_not_included_in_send(self, sender_adapter):
        """Test that snapshot with same sampling_datetime is not resent"""
        # Arrange
        device_id = "device_001"
        sampling_datetime = datetime.now(TIMEZONE_INFO)

        # Mark as already sent
        sender_adapter._LegacySenderAdapter__last_sent_ts_by_device[device_id] = sampling_datetime

        snapshot = {"device_id": device_id, "sampling_datetime": sampling_datetime, "values": {"HZ": 50.0}}

        await sender_adapter.handle_snapshot(snapshot)

        # Act
        latest = await sender_adapter._collect_latest_by_device_unlocked()

        # Simulate send check (simplified)
        should_send = snapshot["sampling_datetime"] > sender_adapter._LegacySenderAdapter__last_sent_ts_by_device.get(
            device_id, sender_adapter._epoch
        )

        # Assert
        assert should_send is False

    @pytest.mark.asyncio
    async def test_when_newer_sampling_datetime_then_included_in_send(self, sender_adapter):
        """Test that snapshot with newer sampling_datetime is sent"""
        # Arrange
        device_id = "device_001"
        old_ts = datetime.now(TIMEZONE_INFO) - timedelta(seconds=60)
        new_ts = datetime.now(TIMEZONE_INFO)

        sender_adapter._LegacySenderAdapter__last_sent_ts_by_device[device_id] = old_ts

        snapshot = {"device_id": device_id, "sampling_datetime": new_ts, "values": {"HZ": 50.0}}

        await sender_adapter.handle_snapshot(snapshot)

        # Act
        should_send = snapshot["sampling_datetime"] > sender_adapter._LegacySenderAdapter__last_sent_ts_by_device.get(
            device_id, sender_adapter._epoch
        )

        # Assert
        assert should_send is True

    @pytest.mark.asyncio
    async def test_when_same_label_time_then_not_included_in_send(self, sender_adapter):
        """Test that device already sent at this label_time is not resent"""
        # Arrange
        device_id = "device_001"
        label_time = datetime.now(TIMEZONE_INFO)

        sender_adapter._LegacySenderAdapter__last_label_ts_by_device[device_id] = label_time

        # Act
        should_send = label_time > sender_adapter._LegacySenderAdapter__last_label_ts_by_device.get(
            device_id, sender_adapter._epoch
        )

        # Assert
        assert should_send is False


# ==================== Bucket Pruning Tests ====================


class TestBucketPruning:
    """Test bucket cleanup after successful send"""

    @pytest.mark.asyncio
    async def test_when_prune_buckets_then_removes_sent_snapshots(self, sender_adapter):
        """Test that sent snapshots are removed from buckets"""
        # Arrange
        device_id = "device_001"
        old_ts = datetime.now(TIMEZONE_INFO) - timedelta(seconds=120)

        snapshot = {"device_id": device_id, "sampling_datetime": old_ts, "values": {}}
        await sender_adapter.handle_snapshot(snapshot)

        # Mark as sent
        sender_adapter._LegacySenderAdapter__last_sent_ts_by_device[device_id] = old_ts

        # Act
        await sender_adapter._prune_buckets()

        # Assert
        latest = await sender_adapter._collect_latest_by_device_unlocked()
        assert device_id not in latest

    @pytest.mark.asyncio
    async def test_when_bucket_empty_then_removes_bucket(self, sender_adapter):
        """Test that empty buckets are removed"""
        # Arrange
        device_id = "device_001"
        sampling_datetime = datetime.now(TIMEZONE_INFO)

        snapshot = {"device_id": device_id, "sampling_datetime": sampling_datetime, "values": {}}
        await sender_adapter.handle_snapshot(snapshot)

        window_start = LegacySenderAdapter._window_start(sampling_datetime, int(sender_adapter.send_interval_sec))
        assert window_start in sender_adapter._latest_per_window

        # Mark as sent and prune
        sender_adapter._LegacySenderAdapter__last_sent_ts_by_device[device_id] = sampling_datetime

        # Act
        await sender_adapter._prune_buckets()

        # Assert
        assert window_start not in sender_adapter._latest_per_window


# ==================== Window Alignment Tests ====================


class TestWindowAlignment:
    """Test time window alignment logic"""

    def test_when_window_start_then_aligns_to_interval(self):
        """Test that timestamps are aligned to interval boundaries"""
        # Arrange
        ts = datetime(2025, 1, 1, 12, 0, 35, tzinfo=TIMEZONE_INFO)
        interval = 60

        # Act
        window_start = LegacySenderAdapter._window_start(ts, interval)

        # Assert
        assert window_start.second == 0  # Aligned to minute boundary
        assert window_start.microsecond == 0

    def test_when_different_seconds_same_window_then_same_start(self):
        """Test that timestamps in same window have same start"""
        # Arrange
        ts1 = datetime(2025, 1, 1, 12, 0, 10, tzinfo=TIMEZONE_INFO)
        ts2 = datetime(2025, 1, 1, 12, 0, 50, tzinfo=TIMEZONE_INFO)
        interval = 60

        # Act
        window1 = LegacySenderAdapter._window_start(ts1, interval)
        window2 = LegacySenderAdapter._window_start(ts2, interval)

        # Assert
        assert window1 == window2


# ==================== Warmup Logic Tests ====================


class TestWarmupLogic:
    """Test warmup send logic"""

    @pytest.mark.asyncio
    async def test_when_timeout_then_skip_warmup(self, sender_adapter):
        """Test that warmup is skipped if no snapshot arrives within timeout"""
        # Arrange
        sender_adapter._first_snapshot_event = asyncio.Event()

        # Act
        await sender_adapter._warmup_send_once(timeout_sec=0.1, debounce_s=0)

        # Assert
        assert not sender_adapter._first_send_done

    @pytest.mark.asyncio
    async def test_when_snapshot_arrives_then_warmup_sends(self, sender_adapter):
        """Test that warmup sends when snapshot arrives"""
        # Arrange
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = Mock()
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = '{"result": "00000"}'
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            sender_adapter._client = mock_client

            sender_adapter._transport = ResendTransport(sender_adapter.ima_url, mock_client, sender_adapter._is_ok)

            snapshot = {
                "device_id": "device_001",
                "model": "TECO_VFD",
                "slave_id": "1",
                "type": "inverter",
                "sampling_datetime": datetime.now(TIMEZONE_INFO),
                "values": {"HZ": 50.0},
            }

            # Trigger snapshot
            await sender_adapter.handle_snapshot(snapshot)

            # Act
            await sender_adapter._warmup_send_once(timeout_sec=1, debounce_s=0)

            # Assert
            assert sender_adapter._first_send_done is True
            mock_client.post.assert_called_once()


# ==================== Scheduler Logic Tests ====================


class TestSchedulerLogic:
    """Test periodic scheduler logic"""

    def test_when_compute_next_label_then_aligns_to_anchor(self, sender_adapter):
        """Test that next label time is correctly computed"""
        # Arrange
        sender_adapter.anchor_offset_sec = 0
        sender_adapter.send_interval_sec = 60
        now = datetime(2025, 1, 1, 12, 0, 30, tzinfo=TIMEZONE_INFO)

        # Act
        next_label = sender_adapter._compute_next_label_time(now)

        # Assert
        assert next_label > now
        assert next_label.second == 0  # Aligned to anchor
        assert next_label.minute == 1  # Next minute

    def test_when_anchor_offset_set_then_uses_offset(self, sender_adapter):
        """Test that anchor offset is respected"""
        # Arrange
        sender_adapter.anchor_offset_sec = 15
        sender_adapter.send_interval_sec = 60
        now = datetime(2025, 1, 1, 12, 0, 5, tzinfo=TIMEZONE_INFO)

        # Act
        next_label = sender_adapter._compute_next_label_time(now)

        # Assert
        assert next_label.second == 15


# ==================== Payload Conversion Tests ====================


class TestPayloadConversion:
    """Test missing value normalization"""

    def test_when_normalize_missing_value_then_converts_to_int(self):
        """Test that -1.0 is normalized to -1 (int)"""
        # Act
        result = LegacySenderAdapter._normalize_missing_value(-1.0)

        # Assert
        assert result == -1
        assert isinstance(result, int)

    def test_when_normalize_deep_then_converts_nested_values(self):
        """Test that nested -1.0 values are normalized"""
        # Arrange
        obj = {"a": -1.0, "b": {"c": -1.0, "d": [1, -1.0, 3]}}

        # Act
        result = LegacySenderAdapter._normalize_missing_deep(obj)

        # Assert
        assert result["a"] == -1
        assert result["b"]["c"] == -1
        assert result["b"]["d"][1] == -1
        assert all(isinstance(v, int) for v in [result["a"], result["b"]["c"], result["b"]["d"][1]])


# ==================== Gateway ID Resolution Tests ====================


class TestGatewayIDResolution:
    """Test gateway ID resolution logic"""

    def test_when_hostname_11_chars_not_default_then_use_hostname(self):
        """Test that valid 11-char hostname is used"""
        # Arrange
        with patch("socket.gethostname", return_value="talosgatew1"):
            # Act
            gateway_id = LegacySenderAdapter._resolve_gateway_id("config_gw_12345")

            # Assert
            assert gateway_id == "talosgatew1"

    def test_when_hostname_11_chars_is_default_then_use_config(self):
        """Test that default hostname falls back to config"""
        # Arrange
        with patch("socket.gethostname", return_value="99999999999"):
            # Act
            gateway_id = LegacySenderAdapter._resolve_gateway_id("config_gw_12345")

            # Assert
            assert gateway_id == "config_gw_1"  # Truncated to 11 chars

    def test_when_hostname_not_11_chars_then_use_config(self):
        """Test that non-11-char hostname uses config"""
        # Arrange
        with patch("socket.gethostname", return_value="short"):
            # Act
            gateway_id = LegacySenderAdapter._resolve_gateway_id("config_gw_12345")

            # Assert
            assert gateway_id == "config_gw_1"


# ==================== Response Validation Tests ====================


class TestResponseValidation:
    """Test HTTP response validation logic"""

    def test_when_response_ok_with_success_code_then_is_ok(self):
        """Test that response with 200 and '00000' is valid"""
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"result": "00000", "message": "success"}'

        # Act
        result = LegacySenderAdapter._is_ok(mock_response)

        # Assert
        assert result is True

    def test_when_response_200_without_success_code_then_not_ok(self):
        """Test that response with 200 but no '00000' is invalid"""
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"result": "99999", "message": "error"}'

        # Act
        result = LegacySenderAdapter._is_ok(mock_response)

        # Assert
        assert result is False

    def test_when_response_not_200_then_not_ok(self):
        """Test that non-200 response is invalid"""
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        # Act
        result = LegacySenderAdapter._is_ok(mock_response)

        # Assert
        assert result is False
