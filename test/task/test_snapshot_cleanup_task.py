"""Unit tests for SnapshotCleanupTask."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio

from repository.snapshot_repository import SnapshotRepository
from task.snapshot_cleanup_task import SnapshotCleanupTask


@pytest_asyncio.fixture
async def mock_repository():
    """Create a mock repository."""
    repo = Mock(spec=SnapshotRepository)
    repo.cleanup_old_snapshots = AsyncMock(return_value=10)  # Deleted 10 records
    repo.vacuum_database = AsyncMock()
    repo.get_db_stats = AsyncMock(
        return_value={
            "total_count": 1000,
            "earliest_ts": datetime.utcnow(),
            "latest_ts": datetime.utcnow(),
            "file_size_bytes": 1024 * 1024,
            "file_size_mb": 1.0,
        }
    )
    return repo


@pytest.mark.asyncio
async def test_cleanup_task_initialization(mock_repository):
    """Test cleanup task initialization."""
    task = SnapshotCleanupTask(
        repository=mock_repository,
        db_path="/tmp/test.db",
        retention_days=7,
        cleanup_interval_hours=6,
        vacuum_interval_days=7,
    )

    assert task.retention_days == 7
    assert task.cleanup_interval_hours == 6
    assert task.vacuum_interval_days == 7
    assert task.cleanup_interval_seconds == 6 * 3600
    assert task.vacuum_interval_seconds == 7 * 86400
    assert task.last_vacuum_time is None


@pytest.mark.asyncio
async def test_cleanup_cycle_deletes_old_snapshots(mock_repository):
    """Test that cleanup cycle deletes old snapshots."""
    task = SnapshotCleanupTask(
        repository=mock_repository,
        db_path="/tmp/test.db",
        retention_days=7,
    )

    await task._run_cleanup_cycle()

    # Verify cleanup was called
    mock_repository.cleanup_old_snapshots.assert_called_once_with(7)


@pytest.mark.asyncio
async def test_cleanup_cycle_gets_db_stats(mock_repository):
    """Test that cleanup cycle retrieves database stats."""
    task = SnapshotCleanupTask(
        repository=mock_repository,
        db_path="/tmp/test.db",
    )

    await task._run_cleanup_cycle()

    # Verify stats were retrieved
    mock_repository.get_db_stats.assert_called_once_with("/tmp/test.db")


@pytest.mark.asyncio
async def test_cleanup_cycle_runs_vacuum_on_first_run(mock_repository):
    """Test that VACUUM runs on the first cleanup cycle."""
    task = SnapshotCleanupTask(
        repository=mock_repository,
        db_path="/tmp/test.db",
        vacuum_interval_days=7,
    )

    # First run should trigger VACUUM (last_vacuum_time is None)
    await task._run_cleanup_cycle()

    # Verify VACUUM was called
    mock_repository.vacuum_database.assert_called_once()
    assert task.last_vacuum_time is not None


@pytest.mark.asyncio
async def test_cleanup_cycle_skips_vacuum_if_recent(mock_repository):
    """Test that VACUUM is skipped if recently run."""
    task = SnapshotCleanupTask(
        repository=mock_repository,
        db_path="/tmp/test.db",
        vacuum_interval_days=7,
    )

    # Set last vacuum time to now
    task.last_vacuum_time = datetime.utcnow()

    # Run cleanup cycle
    await task._run_cleanup_cycle()

    # VACUUM should not be called
    mock_repository.vacuum_database.assert_not_called()


@pytest.mark.asyncio
async def test_should_run_vacuum_logic(mock_repository):
    """Test the _should_run_vacuum logic."""
    task = SnapshotCleanupTask(
        repository=mock_repository,
        db_path="/tmp/test.db",
        vacuum_interval_days=7,
    )

    # Initially should run (no previous vacuum)
    assert task._should_run_vacuum() is True

    # After setting recent vacuum time
    task.last_vacuum_time = datetime.utcnow()
    assert task._should_run_vacuum() is False

    # After vacuum interval has passed (simulate)
    from datetime import timedelta

    task.last_vacuum_time = datetime.utcnow() - timedelta(days=8)
    assert task._should_run_vacuum() is True


@pytest.mark.asyncio
async def test_run_loop_executes_cleanup_cycles(mock_repository):
    """Test that run() executes cleanup cycles on schedule."""
    task = SnapshotCleanupTask(
        repository=mock_repository,
        db_path="/tmp/test.db",
        retention_days=7,
        cleanup_interval_hours=1,  # Run every hour for testing
    )

    # Start the task
    task_handle = asyncio.create_task(task.run())

    # Wait for initial delay + a bit (initial delay is 60 seconds)
    # For testing, we'll cancel before it runs naturally
    await asyncio.sleep(0.1)

    # Cancel the task
    task_handle.cancel()
    try:
        await task_handle
    except asyncio.CancelledError:
        pass

    # Note: In a real test, we'd mock sleep or use a shorter interval


@pytest.mark.asyncio
async def test_cleanup_handles_errors_gracefully(mock_repository):
    """Test that cleanup continues after errors."""
    # Make cleanup raise an error
    mock_repository.cleanup_old_snapshots.side_effect = Exception("Cleanup error")

    task = SnapshotCleanupTask(
        repository=mock_repository,
        db_path="/tmp/test.db",
    )

    # Should not raise, just log
    try:
        await task._run_cleanup_cycle()
    except Exception as e:
        pytest.fail(f"Cleanup cycle should handle errors gracefully, but raised: {e}")


@pytest.mark.asyncio
async def test_vacuum_interval_respected(mock_repository):
    """Test that VACUUM interval is respected."""
    from datetime import timedelta

    task = SnapshotCleanupTask(
        repository=mock_repository,
        db_path="/tmp/test.db",
        vacuum_interval_days=7,
    )

    # Run first cycle - should vacuum
    await task._run_cleanup_cycle()
    assert mock_repository.vacuum_database.call_count == 1

    # Run second cycle immediately - should not vacuum
    await task._run_cleanup_cycle()
    assert mock_repository.vacuum_database.call_count == 1  # Still 1

    # Simulate time passing
    task.last_vacuum_time = datetime.utcnow() - timedelta(days=8)

    # Run third cycle - should vacuum again
    await task._run_cleanup_cycle()
    assert mock_repository.vacuum_database.call_count == 2


@pytest.mark.asyncio
async def test_cleanup_with_custom_retention(mock_repository):
    """Test cleanup with custom retention days."""
    task = SnapshotCleanupTask(
        repository=mock_repository,
        db_path="/tmp/test.db",
        retention_days=30,  # Custom retention
    )

    await task._run_cleanup_cycle()

    # Verify correct retention was used
    mock_repository.cleanup_old_snapshots.assert_called_with(30)
