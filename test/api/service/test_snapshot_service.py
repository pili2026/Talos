"""Unit tests for SnapshotService."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.model.snapshot_responses import (
    CleanupResponse,
    DatabaseStatsResponse,
    RecentSnapshotsResponse,
    SnapshotHistoryResponse,
    SnapshotResponse,
)
from api.service.snapshot_service import SnapshotService
from util.time_util import TIMEZONE_INFO


@pytest.fixture
def mock_snapshot_repo():
    """Create mock SnapshotRepository."""
    repo = MagicMock()
    repo.get_time_range = AsyncMock()
    repo.get_latest_by_device = AsyncMock()
    repo.get_all_recent = AsyncMock()
    repo.get_db_stats = AsyncMock()
    repo.cleanup_old_snapshots = AsyncMock()
    repo.vacuum_database = AsyncMock()
    repo.get_count_in_time_range = AsyncMock()
    return repo


@pytest.fixture
def snapshot_service(mock_snapshot_repo):
    """Create SnapshotService with mocked repository."""
    return SnapshotService(mock_snapshot_repo)


@pytest.fixture
def sample_snapshot_dict():
    """Sample snapshot dictionary from repository."""
    return {
        "id": 1,
        "device_id": "IMA_C_5",
        "model": "IMA_C",
        "slave_id": "5",
        "device_type": "dio",
        "sampling_ts": datetime(2025, 1, 25, 10, 30, 0, tzinfo=TIMEZONE_INFO),
        "created_at": datetime(2025, 1, 25, 10, 30, 1, tzinfo=TIMEZONE_INFO),
        "values": {"DIn01": 1, "DOut01": 0, "AIn01": 12.5},
        "is_online": 1,
    }


class TestGetDeviceHistory:
    """Test get_device_history method."""

    @pytest.mark.asyncio
    async def test_when_snapshots_exist_then_returns_history(
        self, snapshot_service, mock_snapshot_repo, sample_snapshot_dict
    ):
        """Test that device history is returned when snapshots exist."""
        # Arrange
        start = datetime(2025, 1, 25, 0, 0, 0, tzinfo=TIMEZONE_INFO)
        end = datetime(2025, 1, 25, 23, 59, 59, tzinfo=TIMEZONE_INFO)
        mock_snapshot_repo.get_time_range.return_value = [sample_snapshot_dict]
        mock_snapshot_repo.get_count_in_time_range.return_value = 1  # ← 設定 total count

        # Act
        result = await snapshot_service.get_device_history(
            device_id="IMA_C_5",
            start_time=start,
            end_time=end,
            parameters=None,
            limit=1000,
            offset=0,
        )

        # Assert
        assert isinstance(result, SnapshotHistoryResponse)
        assert result.device_id == "IMA_C_5"
        assert result.total_count == 1
        assert len(result.snapshots) == 1
        assert result.limit == 1000
        assert result.offset == 0

        # Verify repository calls
        mock_snapshot_repo.get_time_range.assert_called_once_with(
            device_id="IMA_C_5",
            start_time=start,
            end_time=end,
            limit=1000,
            offset=0,
        )
        mock_snapshot_repo.get_count_in_time_range.assert_called_once_with(
            device_id="IMA_C_5",
            start_time=start,
            end_time=end,
        )

    @pytest.mark.asyncio
    async def test_when_parameters_specified_then_filters_values(
        self, snapshot_service, mock_snapshot_repo, sample_snapshot_dict
    ):
        """Test that parameter filtering works correctly."""
        # Arrange
        start = datetime(2025, 1, 25, 0, 0, 0, tzinfo=TIMEZONE_INFO)
        end = datetime(2025, 1, 25, 23, 59, 59, tzinfo=TIMEZONE_INFO)
        mock_snapshot_repo.get_time_range.return_value = [sample_snapshot_dict]
        mock_snapshot_repo.get_count_in_time_range.return_value = 1  # ← 加上

        # Act
        result = await snapshot_service.get_device_history(
            device_id="IMA_C_5",
            start_time=start,
            end_time=end,
            parameters=["DIn01", "DOut01"],  # Filter out AIn01
            limit=1000,
            offset=0,
        )

        # Assert
        assert result.total_count == 1
        snapshot = result.snapshots[0]
        assert "DIn01" in snapshot.values
        assert "DOut01" in snapshot.values
        assert "AIn01" not in snapshot.values

    @pytest.mark.asyncio
    async def test_when_no_snapshots_found_then_returns_empty_list(self, snapshot_service, mock_snapshot_repo):
        """Test that empty list is returned when no snapshots found."""
        # Arrange
        start = datetime(2025, 1, 25, 0, 0, 0, tzinfo=TIMEZONE_INFO)
        end = datetime(2025, 1, 25, 23, 59, 59, tzinfo=TIMEZONE_INFO)
        mock_snapshot_repo.get_time_range.return_value = []
        mock_snapshot_repo.get_count_in_time_range.return_value = 0  # ← 修正：加上這行

        # Act
        result = await snapshot_service.get_device_history(
            device_id="IMA_C_5",
            start_time=start,
            end_time=end,
            parameters=None,
            limit=1000,
            offset=0,
        )

        # Assert
        assert result.total_count == 0
        assert len(result.snapshots) == 0


class TestGetLatestSnapshot:
    """Test get_latest_snapshot method."""

    @pytest.mark.asyncio
    async def test_when_snapshot_exists_then_returns_latest(
        self, snapshot_service, mock_snapshot_repo, sample_snapshot_dict
    ):
        """Test that latest snapshot is returned when available."""
        # Arrange
        mock_snapshot_repo.get_latest_by_device.return_value = [sample_snapshot_dict]

        # Act
        result = await snapshot_service.get_latest_snapshot(device_id="IMA_C_5", parameters=None)

        # Assert
        assert isinstance(result, SnapshotResponse)
        assert result.device_id == "IMA_C_5"
        assert result.id == 1
        mock_snapshot_repo.get_latest_by_device.assert_called_once_with(device_id="IMA_C_5", limit=1)

    @pytest.mark.asyncio
    async def test_when_no_snapshot_exists_then_returns_none(self, snapshot_service, mock_snapshot_repo):
        """Test that None is returned when no snapshot exists."""
        # Arrange
        mock_snapshot_repo.get_latest_by_device.return_value = []

        # Act
        result = await snapshot_service.get_latest_snapshot(device_id="IMA_C_5", parameters=None)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_when_parameters_specified_then_filters_values(
        self, snapshot_service, mock_snapshot_repo, sample_snapshot_dict
    ):
        """Test that parameter filtering works for latest snapshot."""
        # Arrange
        mock_snapshot_repo.get_latest_by_device.return_value = [sample_snapshot_dict]

        # Act
        result = await snapshot_service.get_latest_snapshot(device_id="IMA_C_5", parameters=["DIn01"])

        # Assert
        assert "DIn01" in result.values
        assert "DOut01" not in result.values
        assert "AIn01" not in result.values


class TestGetRecentSnapshots:
    """Test get_recent_snapshots method."""

    @pytest.mark.asyncio
    async def test_when_recent_snapshots_exist_then_returns_list(
        self, snapshot_service, mock_snapshot_repo, sample_snapshot_dict
    ):
        """Test that recent snapshots are returned from all devices."""
        # Arrange
        mock_snapshot_repo.get_all_recent.return_value = [
            sample_snapshot_dict,
            {**sample_snapshot_dict, "id": 2, "device_id": "SD400_3"},
        ]

        # Act
        result = await snapshot_service.get_recent_snapshots(minutes=10, parameters=None)

        # Assert
        assert isinstance(result, RecentSnapshotsResponse)
        assert result.minutes == 10
        assert result.total_count == 2
        assert len(result.snapshots) == 2
        mock_snapshot_repo.get_all_recent.assert_called_once_with(minutes=10)

    @pytest.mark.asyncio
    async def test_when_parameters_filter_applied_then_filters_values(
        self, snapshot_service, mock_snapshot_repo, sample_snapshot_dict
    ):
        """Test that parameter filtering works for recent snapshots."""
        # Arrange
        mock_snapshot_repo.get_all_recent.return_value = [sample_snapshot_dict]

        # Act
        result = await snapshot_service.get_recent_snapshots(minutes=10, parameters=["DIn01"])

        # Assert
        snapshot = result.snapshots[0]
        assert "DIn01" in snapshot.values
        assert "DOut01" not in snapshot.values


class TestGetDatabaseStats:
    """Test get_database_stats method."""

    @pytest.mark.asyncio
    async def test_when_stats_available_then_returns_statistics(self, snapshot_service, mock_snapshot_repo):
        """Test that database statistics are returned correctly."""
        # Arrange
        mock_stats = {
            "total_count": 1000,
            "earliest_ts": datetime(2025, 1, 18, 0, 0, 0, tzinfo=TIMEZONE_INFO),
            "latest_ts": datetime(2025, 1, 25, 10, 30, 0, tzinfo=TIMEZONE_INFO),
            "file_size_bytes": 10485760,
            "file_size_mb": 10.0,
        }
        mock_snapshot_repo.get_db_stats.return_value = mock_stats

        # Act
        result = await snapshot_service.get_database_stats()

        # Assert
        assert isinstance(result, DatabaseStatsResponse)
        assert result.total_count == 1000
        assert result.file_size_mb == 10.0
        mock_snapshot_repo.get_db_stats.assert_called_once()


class TestCleanupOldSnapshots:
    """Test cleanup_old_snapshots method."""

    @pytest.mark.asyncio
    async def test_when_cleanup_executed_then_returns_deleted_count(self, snapshot_service, mock_snapshot_repo):
        """Test that cleanup operation returns correct deleted count."""
        # Arrange
        mock_snapshot_repo.cleanup_old_snapshots.return_value = 500

        # Act
        result = await snapshot_service.cleanup_old_snapshots(retention_days=7)

        # Assert
        assert isinstance(result, CleanupResponse)
        assert result.deleted_count == 500
        assert result.retention_days == 7
        assert result.status == "success"
        mock_snapshot_repo.cleanup_old_snapshots.assert_called_once_with(retention_days=7)

    @pytest.mark.asyncio
    async def test_when_no_old_snapshots_then_returns_zero_count(self, snapshot_service, mock_snapshot_repo):
        """Test that cleanup returns zero when no old snapshots exist."""
        # Arrange
        mock_snapshot_repo.cleanup_old_snapshots.return_value = 0

        # Act
        result = await snapshot_service.cleanup_old_snapshots(retention_days=7)

        # Assert
        assert result.deleted_count == 0
        assert result.status == "success"


class TestVacuumDatabase:
    """Test vacuum_database method."""

    @pytest.mark.asyncio
    async def test_when_vacuum_succeeds_then_returns_success(self, snapshot_service, mock_snapshot_repo):
        """Test that successful vacuum returns success status."""
        # Arrange
        mock_snapshot_repo.vacuum_database.return_value = None

        # Act
        result = await snapshot_service.vacuum_database()

        # Assert
        assert result["status"] == "success"
        assert "successfully" in result["message"].lower()
        mock_snapshot_repo.vacuum_database.assert_called_once()

    @pytest.mark.asyncio
    async def test_when_vacuum_fails_then_returns_error(self, snapshot_service, mock_snapshot_repo):
        """Test that vacuum failure returns error status."""
        # Arrange
        mock_snapshot_repo.vacuum_database.side_effect = Exception("Database locked")

        # Act
        result = await snapshot_service.vacuum_database()

        # Assert
        assert result["status"] == "error"
        assert "Database locked" in result["message"]


class TestGetDeviceHistoryPagination:
    """Test pagination functionality in get_device_history."""

    @pytest.mark.asyncio
    async def test_when_first_page_requested_then_returns_correct_offset(
        self, snapshot_service, mock_snapshot_repo, sample_snapshot_dict
    ):
        """Test that first page returns offset 0."""
        # Arrange
        start = datetime(2025, 1, 25, 0, 0, 0, tzinfo=TIMEZONE_INFO)
        end = datetime(2025, 1, 25, 23, 59, 59, tzinfo=TIMEZONE_INFO)
        # First page: return 100 items
        mock_snapshot_repo.get_time_range.return_value = [sample_snapshot_dict] * 100
        mock_snapshot_repo.get_count_in_time_range.return_value = 1000

        # Act
        result = await snapshot_service.get_device_history(
            device_id="IMA_C_5",
            start_time=start,
            end_time=end,
            parameters=None,
            limit=100,
            offset=0,
        )

        # Assert
        assert result.offset == 0
        assert result.limit == 100
        assert result.total_count == 1000
        assert len(result.snapshots) == 100
        assert result.page_number == 1
        assert result.total_pages == 10
        assert result.has_next is True
        assert result.has_previous is False
        assert result.next_offset == 100
        assert result.previous_offset is None

    @pytest.mark.asyncio
    async def test_when_second_page_requested_then_returns_correct_offset(
        self, snapshot_service, mock_snapshot_repo, sample_snapshot_dict
    ):
        """Test that second page returns correct pagination metadata."""
        # Arrange
        start = datetime(2025, 1, 25, 0, 0, 0, tzinfo=TIMEZONE_INFO)
        end = datetime(2025, 1, 25, 23, 59, 59, tzinfo=TIMEZONE_INFO)
        # Second page: return 100 items
        mock_snapshot_repo.get_time_range.return_value = [sample_snapshot_dict] * 100
        mock_snapshot_repo.get_count_in_time_range.return_value = 1000

        # Act
        result = await snapshot_service.get_device_history(
            device_id="IMA_C_5",
            start_time=start,
            end_time=end,
            parameters=None,
            limit=100,
            offset=100,  # Second page
        )

        # Assert
        assert result.offset == 100
        assert result.limit == 100
        assert len(result.snapshots) == 100
        assert result.page_number == 2
        assert result.total_pages == 10
        assert result.has_next is True
        assert result.has_previous is True
        assert result.next_offset == 200
        assert result.previous_offset == 0

    @pytest.mark.asyncio
    async def test_when_last_page_requested_then_has_next_is_false(
        self, snapshot_service, mock_snapshot_repo, sample_snapshot_dict
    ):
        """Test that last page correctly indicates no more data."""
        # Arrange
        start = datetime(2025, 1, 25, 0, 0, 0, tzinfo=TIMEZONE_INFO)
        end = datetime(2025, 1, 25, 23, 59, 59, tzinfo=TIMEZONE_INFO)
        # Last page has only 50 items (250 - 200 = 50)
        mock_snapshot_repo.get_time_range.return_value = [sample_snapshot_dict] * 50  # ← 修正：返回 50 筆
        mock_snapshot_repo.get_count_in_time_range.return_value = 250

        # Act - Last page (offset 200, limit 100, total 250)
        result = await snapshot_service.get_device_history(
            device_id="IMA_C_5",
            start_time=start,
            end_time=end,
            parameters=None,
            limit=100,
            offset=200,
        )

        # Assert
        assert result.offset == 200
        assert result.limit == 100
        assert len(result.snapshots) == 50  # Last page only has 50 items
        assert result.total_count == 250
        assert result.page_number == 3
        assert result.total_pages == 3
        assert result.has_next is False  # ← 現在應該正確了
        assert result.has_previous is True
        assert result.next_offset is None
        assert result.previous_offset == 100

    @pytest.mark.asyncio
    async def test_when_middle_page_requested_then_has_both_next_and_previous(
        self, snapshot_service, mock_snapshot_repo, sample_snapshot_dict
    ):
        """Test that middle page indicates both next and previous pages exist."""
        # Arrange
        start = datetime(2025, 1, 25, 0, 0, 0, tzinfo=TIMEZONE_INFO)
        end = datetime(2025, 1, 25, 23, 59, 59, tzinfo=TIMEZONE_INFO)
        # Middle page: return full 100 items
        mock_snapshot_repo.get_time_range.return_value = [sample_snapshot_dict] * 100
        mock_snapshot_repo.get_count_in_time_range.return_value = 500

        # Act - Middle page (offset 200, limit 100, total 500)
        result = await snapshot_service.get_device_history(
            device_id="IMA_C_5",
            start_time=start,
            end_time=end,
            parameters=None,
            limit=100,
            offset=200,
        )

        # Assert
        assert result.offset == 200
        assert result.limit == 100
        assert len(result.snapshots) == 100
        assert result.total_count == 500
        assert result.page_number == 3
        assert result.total_pages == 5
        assert result.has_next is True  # Still has pages after
        assert result.has_previous is True  # Has pages before
        assert result.next_offset == 300
        assert result.previous_offset == 100

    @pytest.mark.asyncio
    async def test_when_exact_last_page_then_has_next_is_false(
        self, snapshot_service, mock_snapshot_repo, sample_snapshot_dict
    ):
        """Test edge case where last page has exactly limit items."""
        # Arrange
        start = datetime(2025, 1, 25, 0, 0, 0, tzinfo=TIMEZONE_INFO)
        end = datetime(2025, 1, 25, 23, 59, 59, tzinfo=TIMEZONE_INFO)
        # Last page with exactly 100 items (300 total, offset 200)
        mock_snapshot_repo.get_time_range.return_value = [sample_snapshot_dict] * 100
        mock_snapshot_repo.get_count_in_time_range.return_value = 300

        # Act
        result = await snapshot_service.get_device_history(
            device_id="IMA_C_5",
            start_time=start,
            end_time=end,
            parameters=None,
            limit=100,
            offset=200,
        )

        # Assert
        assert result.offset == 200
        assert result.limit == 100
        assert len(result.snapshots) == 100
        assert result.total_count == 300
        assert result.page_number == 3
        assert result.total_pages == 3
        # offset (200) + len(snapshots) (100) = 300 == total_count (300)
        assert result.has_next is False  # No more pages
        assert result.has_previous is True
        assert result.next_offset is None
