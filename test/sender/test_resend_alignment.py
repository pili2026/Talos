from datetime import datetime
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from core.schema.sender_schema import CloudConfig, SenderSchema
from core.sender.legacy.legacy_sender import LegacySenderAdapter

TIMEZONE_INFO = ZoneInfo("Asia/Taipei")


class TestResendTimeAlignment:

    @pytest.fixture
    def mock_config(self):
        """Basic configuration"""
        return SenderSchema(
            gateway_id="TEST_GW",
            resend_dir="./test_resend",
            cloud=CloudConfig(ima_url="http://test.com"),
            anchor_offset_sec=15,
            resend_anchor_offset_sec=5,
            fail_resend_interval_sec=120,
            resend_start_delay_sec=180,
        )

    @pytest.fixture
    def mock_device_manager(self):
        """Mock device manager"""
        mock_dm = Mock()
        mock_dm.get_device = Mock(return_value=None)
        return mock_dm

    @pytest.fixture
    def sender_adapter(self, mock_config, system_config_minimal, mock_device_manager):
        """Create a LegacySenderAdapter instance"""
        return LegacySenderAdapter(
            sender_config_schema=mock_config,
            system_config=system_config_minimal,
            device_manager=mock_device_manager,
            series_number=1,
        )

    def test_compute_next_resend_time_basic(self, sender_adapter):
        """Test basic time alignment calculation"""
        # Case: the next aligned time after 12:02:30 should be 12:04:05
        # (Every 120 seconds from midnight: 00:00:05, 00:02:05, 00:04:05, ...)
        after = datetime(2025, 1, 1, 12, 2, 30, tzinfo=TIMEZONE_INFO)
        result = sender_adapter._compute_next_resend_time(after)

        expected = datetime(2025, 1, 1, 12, 4, 5, tzinfo=TIMEZONE_INFO)
        assert result == expected

    def test_compute_next_resend_time_exact_boundary(self, sender_adapter):
        """Test boundary case: exactly on the aligned point"""
        # After 12:04:05 the next should be 12:06:05 (skip the current point)
        after = datetime(2025, 1, 1, 12, 4, 5, tzinfo=TIMEZONE_INFO)
        result = sender_adapter._compute_next_resend_time(after)

        expected = datetime(2025, 1, 1, 12, 6, 5, tzinfo=TIMEZONE_INFO)
        assert result == expected

    def test_compute_next_resend_time_just_before_alignment(self, sender_adapter):
        """Test 1 second before the aligned point"""
        # After 12:04:04 the next should be 12:04:05
        after = datetime(2025, 1, 1, 12, 4, 4, tzinfo=TIMEZONE_INFO)
        result = sender_adapter._compute_next_resend_time(after)

        expected = datetime(2025, 1, 1, 12, 4, 5, tzinfo=TIMEZONE_INFO)
        assert result == expected

    def test_compute_next_resend_time_multiple_intervals(self, sender_adapter):
        """Test across multiple intervals"""
        # 12:00:00 → 12:00:05 (first aligned point)
        after = datetime(2025, 1, 1, 12, 0, 0, tzinfo=TIMEZONE_INFO)
        result = sender_adapter._compute_next_resend_time(after)
        expected = datetime(2025, 1, 1, 12, 0, 5, tzinfo=TIMEZONE_INFO)
        assert result == expected

        # 12:00:05 → 12:02:05
        after = datetime(2025, 1, 1, 12, 0, 5, tzinfo=TIMEZONE_INFO)
        result = sender_adapter._compute_next_resend_time(after)
        expected = datetime(2025, 1, 1, 12, 2, 5, tzinfo=TIMEZONE_INFO)
        assert result == expected

        # 12:02:05 → 12:04:05
        after = datetime(2025, 1, 1, 12, 2, 5, tzinfo=TIMEZONE_INFO)
        result = sender_adapter._compute_next_resend_time(after)
        expected = datetime(2025, 1, 1, 12, 4, 5, tzinfo=TIMEZONE_INFO)
        assert result == expected

    def test_compute_next_resend_time_different_configs(self, system_config_minimal, mock_device_manager):
        """Test different configuration combinations"""
        # Config 1: anchor=0, interval=60 → on the minute
        config1 = SenderSchema(
            gateway_id="TEST",
            resend_dir="./test",
            cloud=CloudConfig(ima_url="http://test.com"),
            resend_anchor_offset_sec=0,
            fail_resend_interval_sec=60,
        )
        adapter1 = LegacySenderAdapter(
            sender_config_schema=config1,
            device_manager=mock_device_manager,
            series_number=1,
            system_config=system_config_minimal,
        )

        after = datetime(2025, 1, 1, 12, 0, 30, tzinfo=TIMEZONE_INFO)
        result = adapter1._compute_next_resend_time(after)
        expected = datetime(2025, 1, 1, 12, 1, 0, tzinfo=TIMEZONE_INFO)
        assert result == expected

        # Config 2: anchor=45, interval=300 (5 minutes) → XX:00:45, XX:05:45, XX:10:45
        config2 = SenderSchema(
            gateway_id="TEST",
            resend_dir="./test",
            cloud=CloudConfig(ima_url="http://test.com"),
            resend_anchor_offset_sec=45,
            fail_resend_interval_sec=300,
        )
        adapter2 = LegacySenderAdapter(
            sender_config_schema=config2,
            device_manager=mock_device_manager,
            series_number=1,
            system_config=system_config_minimal,
        )

        after = datetime(2025, 1, 1, 12, 3, 0, tzinfo=TIMEZONE_INFO)
        result = adapter2._compute_next_resend_time(after)
        expected = datetime(2025, 1, 1, 12, 5, 45, tzinfo=TIMEZONE_INFO)
        assert result == expected

    def test_schema_validation_anchor_offset_range(self):
        """Test schema validation: anchor must not exceed interval"""
        with pytest.raises(ValueError, match="must be less than"):
            SenderSchema(
                gateway_id="TEST",
                resend_dir="./test",
                cloud=CloudConfig(ima_url="http://test.com"),
                resend_anchor_offset_sec=130,  # exceeds interval
                fail_resend_interval_sec=120,
            )

    def test_alignment_consistency_over_time(self, sender_adapter):
        """Test alignment consistency over time (multiple calls should keep interval spacing)"""
        # Starting from a given time, compute 5 consecutive alignments
        current = datetime(2025, 1, 1, 12, 0, 0, tzinfo=TIMEZONE_INFO)
        results = []

        for _ in range(5):
            next_time = sender_adapter._compute_next_resend_time(current)
            results.append(next_time)
            current = next_time

        # Validate each interval is 120 seconds
        expected_times = [
            datetime(2025, 1, 1, 12, 0, 5, tzinfo=TIMEZONE_INFO),
            datetime(2025, 1, 1, 12, 2, 5, tzinfo=TIMEZONE_INFO),
            datetime(2025, 1, 1, 12, 4, 5, tzinfo=TIMEZONE_INFO),
            datetime(2025, 1, 1, 12, 6, 5, tzinfo=TIMEZONE_INFO),
            datetime(2025, 1, 1, 12, 8, 5, tzinfo=TIMEZONE_INFO),
        ]

        assert results == expected_times

        # Validate interval consistency
        for i in range(1, len(results)):
            interval = (results[i] - results[i - 1]).total_seconds()
            assert interval == 120.0

    def test_compute_next_resend_time_cross_hour(self, sender_adapter):
        """Test crossing an hour boundary"""
        # 11:58:30 → 12:00:05
        after = datetime(2025, 1, 1, 11, 58, 30, tzinfo=TIMEZONE_INFO)
        result = sender_adapter._compute_next_resend_time(after)
        expected = datetime(2025, 1, 1, 12, 0, 5, tzinfo=TIMEZONE_INFO)
        assert result == expected

    def test_compute_next_resend_time_cross_day(self, system_config_minimal, mock_device_manager):
        """Test crossing a day boundary"""
        config = SenderSchema(
            gateway_id="TEST",
            resend_dir="./test",
            cloud=CloudConfig(ima_url="http://test.com"),
            resend_anchor_offset_sec=30,
            fail_resend_interval_sec=3600,  # 1 hour
        )
        adapter = LegacySenderAdapter(
            sender_config_schema=config,
            device_manager=mock_device_manager,
            series_number=1,
            system_config=system_config_minimal,
        )

        # 23:45:00 → 2025-01-02 00:00:30
        after = datetime(2025, 1, 1, 23, 45, 0, tzinfo=TIMEZONE_INFO)
        result = adapter._compute_next_resend_time(after)
        expected = datetime(2025, 1, 2, 0, 0, 30, tzinfo=TIMEZONE_INFO)
        assert result == expected

    def test_compute_next_resend_time_naive_datetime(self, sender_adapter):
        """Test handling of naive datetime (should auto-attach timezone)"""
        after_naive = datetime(2025, 1, 1, 12, 2, 30)  # no tzinfo
        result = sender_adapter._compute_next_resend_time(after_naive)

        expected = datetime(2025, 1, 1, 12, 4, 5, tzinfo=TIMEZONE_INFO)
        assert result == expected
        assert result.tzinfo is not None

    def test_alignment_pattern_verification(self, sender_adapter):
        """Verify alignment pattern: every 120 seconds starting from midnight"""
        # First few aligned points from midnight
        midnight = datetime(2025, 1, 1, 0, 0, 0, tzinfo=TIMEZONE_INFO)

        # Compute the first 10 aligned times
        current = midnight
        alignments = []
        for _ in range(10):
            next_aligned = sender_adapter._compute_next_resend_time(current)
            alignments.append(next_aligned)
            current = next_aligned

        # Expected pattern: 00:00:05, 00:02:05, 00:04:05, ...
        expected_pattern = [
            datetime(2025, 1, 1, 0, 0, 5, tzinfo=TIMEZONE_INFO),
            datetime(2025, 1, 1, 0, 2, 5, tzinfo=TIMEZONE_INFO),
            datetime(2025, 1, 1, 0, 4, 5, tzinfo=TIMEZONE_INFO),
            datetime(2025, 1, 1, 0, 6, 5, tzinfo=TIMEZONE_INFO),
            datetime(2025, 1, 1, 0, 8, 5, tzinfo=TIMEZONE_INFO),
            datetime(2025, 1, 1, 0, 10, 5, tzinfo=TIMEZONE_INFO),
            datetime(2025, 1, 1, 0, 12, 5, tzinfo=TIMEZONE_INFO),
            datetime(2025, 1, 1, 0, 14, 5, tzinfo=TIMEZONE_INFO),
            datetime(2025, 1, 1, 0, 16, 5, tzinfo=TIMEZONE_INFO),
            datetime(2025, 1, 1, 0, 18, 5, tzinfo=TIMEZONE_INFO),
        ]

        assert alignments == expected_pattern
