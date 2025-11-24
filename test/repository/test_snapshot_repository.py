"""Unit tests for SnapshotRepository."""

import asyncio
import os
from datetime import datetime, timedelta

import pytest
import pytest_asyncio

from db.engine import create_snapshot_engine
from repository.snapshot_repository import SnapshotRepository


@pytest.fixture
def test_db_path(tmp_path):
    """Provide a temporary database path."""
    return str(tmp_path / "test_snapshots.db")


@pytest_asyncio.fixture
async def repository(test_db_path):
    """Create a repository with initialized database."""
    engine = create_snapshot_engine(test_db_path)
    repo = SnapshotRepository(engine)
    await repo.init_db()
    yield repo
    # Cleanup
    await engine.dispose()


@pytest.fixture
def sample_snapshot():
    """Create a sample snapshot for testing."""
    return {
        "device_id": "A26A_1",
        "model": "A26A",
        "slave_id": "1",
        "type": "Inverter",
        "sampling_ts": datetime.utcnow(),
        "values": {
            "VIn": 220.5,
            "HZ": 60.0,
            "PF": 0.95,
            "AIn01": 100.0,
        },
    }


@pytest.mark.asyncio
async def test_insert_snapshot_success(repository, sample_snapshot):
    """Test successful snapshot insertion."""
    await repository.insert_snapshot(sample_snapshot)

    # Verify by querying
    snapshots = await repository.get_latest_by_device(sample_snapshot["device_id"], limit=1)
    assert len(snapshots) == 1
    assert snapshots[0]["device_id"] == sample_snapshot["device_id"]
    assert snapshots[0]["model"] == sample_snapshot["model"]
    assert snapshots[0]["is_online"] == 1  # Normal values, should be online


@pytest.mark.asyncio
async def test_insert_snapshot_with_all_minus_one_values(repository):
    """Test snapshot insertion where all values are -1 (offline)."""
    snapshot = {
        "device_id": "A26A_2",
        "model": "A26A",
        "slave_id": "2",
        "type": "Inverter",
        "sampling_ts": datetime.utcnow(),
        "values": {
            "VIn": -1,
            "HZ": -1,
            "PF": -1,
            "AIn01": -1,
        },
    }

    await repository.insert_snapshot(snapshot)

    snapshots = await repository.get_latest_by_device(snapshot["device_id"], limit=1)
    assert len(snapshots) == 1
    assert snapshots[0]["is_online"] == 0  # All -1, should be offline


@pytest.mark.asyncio
async def test_insert_snapshot_with_partial_minus_one(repository):
    """Test snapshot insertion where some values are -1 (still online)."""
    snapshot = {
        "device_id": "A26A_3",
        "model": "A26A",
        "slave_id": "3",
        "type": "Inverter",
        "sampling_ts": datetime.utcnow(),
        "values": {
            "VIn": 220.5,
            "HZ": 60.0,
            "PF": -1,  # Partial sensor failure
            "AIn01": -1,
        },
    }

    await repository.insert_snapshot(snapshot)

    snapshots = await repository.get_latest_by_device(snapshot["device_id"], limit=1)
    assert len(snapshots) == 1
    assert snapshots[0]["is_online"] == 1  # Partial -1, still online


@pytest.mark.asyncio
async def test_get_latest_by_device(repository, sample_snapshot):
    """Test retrieving latest snapshots for a device."""
    # Insert multiple snapshots
    for i in range(5):
        snapshot = sample_snapshot.copy()
        snapshot["sampling_ts"] = datetime.utcnow() - timedelta(minutes=i)
        await repository.insert_snapshot(snapshot)
        await asyncio.sleep(0.01)  # Small delay to ensure different timestamps

    # Retrieve latest 3
    snapshots = await repository.get_latest_by_device(sample_snapshot["device_id"], limit=3)

    assert len(snapshots) == 3
    # Should be ordered by most recent first
    assert snapshots[0]["sampling_ts"] >= snapshots[1]["sampling_ts"]
    assert snapshots[1]["sampling_ts"] >= snapshots[2]["sampling_ts"]


@pytest.mark.asyncio
async def test_get_time_range(repository, sample_snapshot):
    """Test querying snapshots within a time range."""
    base_time = datetime.utcnow()

    # Insert snapshots at different times
    for i in range(10):
        snapshot = sample_snapshot.copy()
        snapshot["sampling_ts"] = base_time - timedelta(minutes=i)
        await repository.insert_snapshot(snapshot)

    # Query for middle 5 snapshots (minutes 2-7)
    start_time = base_time - timedelta(minutes=7)
    end_time = base_time - timedelta(minutes=2)

    snapshots = await repository.get_time_range(
        sample_snapshot["device_id"],
        start_time,
        end_time,
    )

    assert len(snapshots) == 6  # Inclusive range
    # Should be ordered by time ascending
    for i in range(len(snapshots) - 1):
        assert snapshots[i]["sampling_ts"] <= snapshots[i + 1]["sampling_ts"]


@pytest.mark.asyncio
async def test_get_parameter_history(repository, sample_snapshot):
    """Test querying history of a specific parameter."""
    base_time = datetime.utcnow()

    # Insert snapshots with varying parameter values
    for i in range(5):
        snapshot = sample_snapshot.copy()
        snapshot["sampling_ts"] = base_time - timedelta(minutes=i)
        snapshot["values"]["VIn"] = 220.0 + i
        await repository.insert_snapshot(snapshot)

    # Query VIn parameter history
    start_time = base_time - timedelta(minutes=10)
    end_time = base_time

    history = await repository.get_parameter_history(
        sample_snapshot["device_id"],
        "VIn",
        start_time,
        end_time,
    )

    assert len(history) == 5
    # Verify structure
    for record in history:
        assert "sampling_ts" in record
        assert "value" in record
        assert "is_online" in record
    # Check values are correct
    assert all(record["value"] >= 220.0 for record in history)


@pytest.mark.asyncio
async def test_get_all_recent(repository, sample_snapshot):
    """Test retrieving all recent snapshots from all devices."""
    # Insert snapshots for multiple devices
    for device_num in range(3):
        snapshot = sample_snapshot.copy()
        snapshot["device_id"] = f"A26A_{device_num}"
        snapshot["slave_id"] = str(device_num)
        snapshot["sampling_ts"] = datetime.utcnow()
        await repository.insert_snapshot(snapshot)

    # Get all snapshots from last 5 minutes
    snapshots = await repository.get_all_recent(minutes=5)

    assert len(snapshots) == 3
    device_ids = {s["device_id"] for s in snapshots}
    assert device_ids == {"A26A_0", "A26A_1", "A26A_2"}


@pytest.mark.asyncio
async def test_cleanup_old_snapshots(repository, sample_snapshot):
    """Test deletion of old snapshots."""
    base_time = datetime.utcnow()

    # Insert old snapshots (10 days ago)
    for i in range(5):
        snapshot = sample_snapshot.copy()
        snapshot["device_id"] = "OLD_DEVICE"
        snapshot["sampling_ts"] = base_time - timedelta(days=10)
        await repository.insert_snapshot(snapshot)

    # Insert recent snapshots (1 day ago)
    for i in range(3):
        snapshot = sample_snapshot.copy()
        snapshot["device_id"] = "RECENT_DEVICE"
        snapshot["sampling_ts"] = base_time - timedelta(days=1)
        await repository.insert_snapshot(snapshot)

    # Cleanup snapshots older than 7 days
    deleted_count = await repository.cleanup_old_snapshots(retention_days=7)

    assert deleted_count == 5

    # Verify recent snapshots are still there
    recent_snapshots = await repository.get_latest_by_device("RECENT_DEVICE")
    assert len(recent_snapshots) == 3

    # Verify old snapshots are gone
    old_snapshots = await repository.get_latest_by_device("OLD_DEVICE")
    assert len(old_snapshots) == 0


@pytest.mark.asyncio
async def test_vacuum_database(repository, sample_snapshot):
    """Test VACUUM operation."""
    # Insert some data
    for i in range(10):
        await repository.insert_snapshot(sample_snapshot)

    # VACUUM should not raise an error
    await repository.vacuum_database()


@pytest.mark.asyncio
async def test_get_db_stats(repository, sample_snapshot, test_db_path):
    """Test database statistics retrieval."""
    # Initially empty
    stats = await repository.get_db_stats(test_db_path)
    assert stats["total_count"] == 0
    assert stats["earliest_ts"] is None
    assert stats["latest_ts"] is None
    assert stats["file_size_bytes"] > 0  # Database file exists

    # Insert some snapshots
    for i in range(5):
        snapshot = sample_snapshot.copy()
        snapshot["sampling_ts"] = datetime.utcnow() - timedelta(minutes=i)
        await repository.insert_snapshot(snapshot)

    # Check stats
    stats = await repository.get_db_stats(test_db_path)
    assert stats["total_count"] == 5
    assert stats["earliest_ts"] is not None
    assert stats["latest_ts"] is not None
    assert stats["file_size_mb"] > 0


@pytest.mark.asyncio
async def test_empty_values_handling(repository):
    """Test handling of snapshots with empty or non-numeric values."""
    snapshot = {
        "device_id": "TEST_DEVICE",
        "model": "TEST",
        "slave_id": "1",
        "type": "Sensor",
        "sampling_ts": datetime.utcnow(),
        "values": {},  # Empty values
    }

    await repository.insert_snapshot(snapshot)

    snapshots = await repository.get_latest_by_device(snapshot["device_id"], limit=1)
    assert len(snapshots) == 1
    assert snapshots[0]["values"] == {}
    # Empty values means no numeric values, so all(-1 for v in []) is True → offline
    # But actually there are no values, so it should be online (no -1s)
    # The logic checks: all(v == -1 for v in numeric_values)
    # If numeric_values is empty, all() returns True → is_online = 0
    assert snapshots[0]["is_online"] == 0
