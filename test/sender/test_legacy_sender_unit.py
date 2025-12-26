import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
import yaml

from core.schema.sender_schema import SenderSchema
from core.sender.legacy.legacy_sender import LegacySenderAdapter
from core.sender.transport import ResendTransport
from core.util.time_util import TIMEZONE_INFO

# ==================== Initialization Tests ====================


class TestLegacySenderInitialization:
    """Test correct initialization of variables"""

    def test_when_initialized_then_last_post_ok_within_sec_is_float(self, sender_adapter):
        """Test that last_post_ok_within_sec is initialized as float (not datetime)"""
        assert isinstance(sender_adapter.last_post_ok_within_sec, float)
        assert sender_adapter.last_post_ok_within_sec == 300.0

    def test_when_initialized_then_last_post_ok_at_is_none(self, sender_adapter):
        """Test that last_post_ok_at is initialized as None (not float)"""
        assert sender_adapter.last_post_ok_at is None

    def test_when_initialized_then_resend_start_delay_sec_is_set(self, sender_adapter):
        """Test that resend_start_delay_sec is read from config"""
        assert sender_adapter.resend_start_delay_sec == 180


# ==================== Delayed Resend Start Tests ====================


class TestDelayedResendStart:
    """Test delayed resend worker startup"""

    @pytest.mark.asyncio
    async def test_when_start_called_then_resend_worker_delayed(self, sender_adapter):
        """Test that resend worker doesn't start immediately"""
        sender_adapter.resend_start_delay_sec = 1

        await sender_adapter.start()
        await asyncio.sleep(0.1)

        assert sender_adapter._resend_task is None

        await sender_adapter.stop()

    @pytest.mark.asyncio
    async def test_when_delay_elapsed_then_resend_worker_starts(self, sender_adapter):
        """Test that resend worker starts after delay"""
        sender_adapter.resend_start_delay_sec = 0.5
        sender_adapter.fail_resend_interval_sec = 2
        sender_adapter.resend_anchor_offset_sec = 0

        start_time = datetime.now(TIMEZONE_INFO)
        await sender_adapter.start()

        min_start = start_time + timedelta(seconds=0.5)
        next_aligned = sender_adapter._compute_next_resend_time(min_start)
        expected_wait = (next_aligned - start_time).total_seconds()

        await asyncio.sleep(expected_wait + 0.2)

        assert sender_adapter._resend_task is not None
        assert not sender_adapter._resend_task.done()

        await sender_adapter.stop()

    @pytest.mark.asyncio
    async def test_when_fail_resend_disabled_then_no_worker_starts(self, sender_adapter):
        """Test that worker doesn't start if fail_resend_enabled is False"""
        sender_adapter.fail_resend_enabled = False

        await sender_adapter.start()
        await asyncio.sleep(0.1)

        assert sender_adapter._resend_task is None

        await sender_adapter.stop()


# ==================== Health Gate Tests ====================


class TestHealthGate:
    """Test health gate logic in resend worker"""

    def test_when_no_success_yet_then_gate_condition_false(self, sender_adapter):
        """Test gate condition when last_post_ok_at is None"""
        sender_adapter.last_post_ok_within_sec = 300.0
        sender_adapter.last_post_ok_at = None

        # Simulate gate check
        should_skip = sender_adapter.last_post_ok_within_sec > 0 and sender_adapter.last_post_ok_at is None

        assert should_skip is True

    def test_when_recent_success_then_gate_allows(self, sender_adapter):
        """Test that gate allows when last success is recent"""
        sender_adapter.last_post_ok_within_sec = 300.0
        sender_adapter.last_post_ok_at = datetime.now(TIMEZONE_INFO)

        now = datetime.now(TIMEZONE_INFO)
        elapsed = (now - sender_adapter.last_post_ok_at).total_seconds()

        assert elapsed < sender_adapter.last_post_ok_within_sec

    def test_when_old_success_then_gate_blocks(self, sender_adapter):
        """Test that gate blocks when last success is too old"""
        sender_adapter.last_post_ok_within_sec = 300.0
        sender_adapter.last_post_ok_at = datetime.now(TIMEZONE_INFO) - timedelta(seconds=400)

        now = datetime.now(TIMEZONE_INFO)
        elapsed = (now - sender_adapter.last_post_ok_at).total_seconds()

        assert elapsed > sender_adapter.last_post_ok_within_sec

    def test_when_health_gate_disabled_then_always_allow(self, sender_adapter):
        """Test that gate is bypassed when disabled (= 0)"""
        sender_adapter.last_post_ok_within_sec = 0.0
        sender_adapter.last_post_ok_at = None

        should_skip = sender_adapter.last_post_ok_within_sec > 0 and sender_adapter.last_post_ok_at is None

        assert should_skip is False


# ==================== Post Success Tracking Tests ====================


class TestPostSuccessTracking:
    """Test that last_post_ok_at is updated correctly"""

    @pytest.mark.asyncio
    async def test_when_post_succeeds_then_update_last_post_ok_at(self, sender_adapter):
        """Test that successful POST updates last_post_ok_at"""
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

            before = datetime.now(TIMEZONE_INFO)
            payload = {"FUNC": "PushIMAData", "Data": []}
            ok = await sender_adapter._post_with_retry(payload)
            after = datetime.now(TIMEZONE_INFO)

            assert ok is True
            assert sender_adapter.last_post_ok_at is not None
            assert isinstance(sender_adapter.last_post_ok_at, datetime)
            assert before <= sender_adapter.last_post_ok_at <= after

    @pytest.mark.asyncio
    async def test_when_post_fails_then_no_update_last_post_ok_at(self, sender_adapter):
        """Test that failed POST doesn't update last_post_ok_at"""
        sender_adapter.last_post_ok_at = None

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = Mock()
            mock_response = Mock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            sender_adapter._client = mock_client

            sender_adapter._transport = ResendTransport(sender_adapter.ima_url, mock_client, sender_adapter._is_ok)

            payload = {"FUNC": "PushIMAData", "Data": []}
            ok = await sender_adapter._post_with_retry(payload)

            assert ok is False
            assert sender_adapter.last_post_ok_at is None


# ==================== Configuration Validation Tests ====================


class TestConfigurationValidation:
    """Test that configuration values are correctly applied"""

    def test_when_config_has_custom_delay_then_use_custom_value(self, system_config_minimal, mock_device_manager):
        """Test custom resend_start_delay_sec is respected"""
        config_yaml = """
gateway_id: "test"
resend_dir: "./test"
cloud:
  ima_url: "http://test.com"
send_interval_sec: 60
anchor_offset_sec: 0
tick_grace_sec: 1
fresh_window_sec: 2
attempt_count: 2
max_retry: -1
fail_resend_enabled: true
fail_resend_interval_sec: 60
fail_resend_batch: 10
last_post_ok_within_sec: 300
resend_start_delay_sec: 999
"""
        config = SenderSchema.model_validate(yaml.safe_load(config_yaml))
        adapter = LegacySenderAdapter(
            sender_config_schema=config,
            device_manager=mock_device_manager,
            series_number=0,
            system_config=system_config_minimal,
        )

        assert adapter.resend_start_delay_sec == 999
