import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest

from core.util.time_util import TIMEZONE_INFO


class TestLegacySenderIntegration:
    """Integration test for complete flow"""

    @pytest.mark.asyncio
    async def test_warmup_sends_immediately(self, sender_adapter):
        """Test that warmup sends immediately after first snapshot"""
        with patch("httpx.AsyncClient") as mock_client_class:
            # ---- Prepare response ----
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = '{"result": "00000"}'
            mock_response.json = Mock(return_value={"result": "00000"})
            mock_response.raise_for_status = Mock(return_value=None)

            # ---- Prepare client ----
            mock_client = Mock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()

            # >>> Important: support async with <<<
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            mock_client_class.return_value = mock_client

            await sender_adapter.start()

            snapshot = {
                "device_id": "test_device",
                "model": "TECO_VFD",
                "slave_id": "1",
                "type": "inverter",
                "sampling_datetime": datetime.now(TIMEZONE_INFO),
                "values": {"HZ": 50.0},
            }

            await sender_adapter.handle_snapshot(snapshot)

            # If warmup has debounce, extend wait time slightly
            await asyncio.sleep(1.2)

            assert mock_client.post.called, "HTTP POST should be called during warmup"
            assert sender_adapter.last_post_ok_at is not None, "Warmup should set last_post_ok_at after successful send"

    @pytest.mark.asyncio
    async def test_complete_startup_flow_with_delayed_resend(self, sender_adapter):
        """Test complete startup: warmup → scheduler → delayed resend"""
        sender_adapter.resend_start_delay_sec = 0.5
        sender_adapter.fail_resend_interval_sec = 2
        sender_adapter.resend_anchor_offset_sec = 10

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = Mock()
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = '{"result": "00000"}'
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            start_time = datetime.now(TIMEZONE_INFO)
            await sender_adapter.start()

            snapshot = {
                "device_id": "test_device",
                "model": "TECO_VFD",
                "slave_id": "1",
                "type": "inverter",
                "sampling_datetime": datetime.now(TIMEZONE_INFO),
                "values": {"HZ": 50.0},
            }

            await sender_adapter.handle_snapshot(snapshot)

            # Compute expected resend worker start time
            min_start = start_time + timedelta(seconds=0.5)
            next_aligned = sender_adapter._compute_next_resend_time(min_start)
            wait_time = (next_aligned - start_time).total_seconds()

            # Wait for warmup + resend
            await asyncio.sleep(wait_time + 0.5)

            assert sender_adapter._resend_task is not None
            assert sender_adapter.last_post_ok_at is not None

    @pytest.mark.asyncio
    async def test_multiple_snapshots_deduplicated(self, sender_adapter):
        """Test that duplicate snapshots are not resent"""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = Mock()
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = '{"result": "00000"}'
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            await sender_adapter.start()

            # Same sampling_datetime
            same_ts = datetime.now(TIMEZONE_INFO)
            snapshot1 = {
                "device_id": "test_device",
                "model": "TECO_VFD",
                "slave_id": "1",
                "type": "inverter",
                "sampling_datetime": same_ts,
                "values": {"HZ": 50.0},
            }
            snapshot2 = {
                "device_id": "test_device",
                "model": "TECO_VFD",
                "slave_id": "1",
                "type": "inverter",
                "sampling_datetime": same_ts,  # Same timestamp
                "values": {"HZ": 55.0},  # Different value
            }

            await sender_adapter.handle_snapshot(snapshot1)
            await asyncio.sleep(0.3)  # Wait for warmup

            initial_call_count = mock_client.post.call_count

            await sender_adapter.handle_snapshot(snapshot2)
            await asyncio.sleep(0.3)

            # The second snapshot should not trigger a new send
            assert mock_client.post.call_count == initial_call_count

    @pytest.mark.asyncio
    async def test_failed_send_does_not_update_last_post_ok(self, sender_adapter):
        """Test that failed sends don't update last_post_ok_at"""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = Mock()
            mock_response = Mock()
            mock_response.status_code = 500  # Failure
            mock_response.text = '{"error": "server error"}'
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            await sender_adapter.start()

            snapshot = {
                "device_id": "test_device",
                "model": "TECO_VFD",
                "slave_id": "1",
                "type": "inverter",
                "sampling_datetime": datetime.now(TIMEZONE_INFO),
                "values": {"HZ": 50.0},
            }

            await sender_adapter.handle_snapshot(snapshot)
            await asyncio.sleep(0.5)

            # Failed sends should not set last_post_ok_at
            assert sender_adapter.last_post_ok_at is None
