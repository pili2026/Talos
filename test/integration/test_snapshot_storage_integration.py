"""Integration tests for complete snapshot storage flow."""

import asyncio
from datetime import datetime, timedelta

import pytest
import pytest_asyncio

from db.engine import create_snapshot_engine
from repository.snapshot_repository import SnapshotRepository
from task.snapshot_cleanup_task import SnapshotCleanupTask
from util.pubsub.in_memory_pubsub import InMemoryPubSub
from util.pubsub.pubsub_topic import PubSubTopic
from util.pubsub.subscriber.snapshot_saver_subscriber import SnapshotSaverSubscriber


@pytest.fixture
def test_db_path(tmp_path):
    """Provide a temporary database path."""
    return str(tmp_path / "test_integration.db")


@pytest_asyncio.fixture
async def full_stack(test_db_path):
    """
    Create a complete snapshot storage stack.

    Returns:
        Tuple of (pubsub, repository, subscriber, cleanup_task)
    """
    # Create components
    pubsub = InMemoryPubSub()
    engine = create_snapshot_engine(test_db_path)
    repository = SnapshotRepository(engine)

    # Initialize database
    await repository.init_db()

    # Create subscriber
    subscriber = SnapshotSaverSubscriber(pubsub, repository)

    # Create cleanup task (with short intervals for testing)
    cleanup_task = SnapshotCleanupTask(
        repository=repository,
        db_path=test_db_path,
        retention_days=1,
        cleanup_interval_hours=1,
        vacuum_interval_days=1,
    )

    yield pubsub, repository, subscriber, cleanup_task

    # Cleanup
    await engine.dispose()


@pytest.mark.asyncio
async def test_end_to_end_snapshot_flow(full_stack):
    """
    Test complete snapshot flow:
    1. Publish snapshot via PubSub
    2. Subscriber receives and saves to DB
    3. Repository can query the data
    """
    pubsub, repository, subscriber, _ = full_stack

    # Start subscriber in background
    subscriber_task = asyncio.create_task(subscriber.run())
    await asyncio.sleep(0.1)  # Let subscriber start

    # Publish a snapshot (simulating DeviceMonitor)
    snapshot = {
        "device_id": "A26A_1",
        "model": "A26A",
        "slave_id": "1",
        "type": "Inverter",
        "sampling_ts": datetime.utcnow(),
        "values": {
            "VIn": 220.5,
            "HZ": 60.0,
            "PF": 0.95,
        },
    }

    await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, snapshot)

    # Wait for processing
    await asyncio.sleep(0.2)

    # Verify data was saved
    snapshots = await repository.get_latest_by_device("A26A_1", limit=1)
    assert len(snapshots) == 1
    assert snapshots[0]["device_id"] == "A26A_1"
    assert snapshots[0]["model"] == "A26A"
    assert snapshots[0]["values"]["VIn"] == 220.5
    assert snapshots[0]["is_online"] == 1

    # Cleanup
    subscriber_task.cancel()
    try:
        await subscriber_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_multiple_devices_snapshot_flow(full_stack):
    """Test handling snapshots from multiple devices."""
    pubsub, repository, subscriber, _ = full_stack

    # Start subscriber
    subscriber_task = asyncio.create_task(subscriber.run())
    await asyncio.sleep(0.1)

    # Publish snapshots from 3 different devices
    devices = [
        {"device_id": "A26A_1", "model": "A26A", "type": "Inverter"},
        {"device_id": "ADAM4117_2", "model": "ADAM4117", "type": "AI_Module"},
        {"device_id": "JY_DAM0816D_3", "model": "JY_DAM0816D", "type": "DI_Module"},
    ]

    for device in devices:
        snapshot = {
            **device,
            "slave_id": device["device_id"].split("_")[1],
            "sampling_ts": datetime.utcnow(),
            "values": {"value1": 100.0, "value2": 200.0},
        }
        await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, snapshot)

    # Wait for processing
    await asyncio.sleep(0.3)

    # Verify all devices were saved
    for device in devices:
        snapshots = await repository.get_latest_by_device(device["device_id"], limit=1)
        assert len(snapshots) == 1
        assert snapshots[0]["device_id"] == device["device_id"]
        assert snapshots[0]["model"] == device["model"]

    # Cleanup
    subscriber_task.cancel()
    try:
        await subscriber_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_cleanup_integration(full_stack, test_db_path):
    """Test cleanup task integration with repository."""
    pubsub, repository, subscriber, cleanup_task = full_stack

    # Insert old snapshots (2 days ago)
    old_time = datetime.utcnow() - timedelta(days=2)
    for i in range(5):
        snapshot = {
            "device_id": "OLD_DEVICE",
            "model": "TEST",
            "slave_id": "1",
            "type": "Sensor",
            "sampling_ts": old_time,
            "values": {"temp": 25.0},
        }
        await repository.insert_snapshot(snapshot)

    # Insert recent snapshots (now)
    for i in range(3):
        snapshot = {
            "device_id": "RECENT_DEVICE",
            "model": "TEST",
            "slave_id": "2",
            "type": "Sensor",
            "sampling_ts": datetime.utcnow(),
            "values": {"temp": 25.0},
        }
        await repository.insert_snapshot(snapshot)

    # Verify all snapshots are there
    all_snapshots = await repository.get_all_recent(minutes=10000)
    assert len(all_snapshots) == 8

    # Run cleanup cycle (retention_days=1, so old snapshots should be deleted)
    await cleanup_task._run_cleanup_cycle()

    # Verify old snapshots were deleted
    old_snapshots = await repository.get_latest_by_device("OLD_DEVICE")
    assert len(old_snapshots) == 0

    # Verify recent snapshots are still there
    recent_snapshots = await repository.get_latest_by_device("RECENT_DEVICE")
    assert len(recent_snapshots) == 3

    # Verify VACUUM was run (last_vacuum_time should be set)
    assert cleanup_task.last_vacuum_time is not None


@pytest.mark.asyncio
async def test_time_series_query_integration(full_stack):
    """Test querying time series data."""
    pubsub, repository, subscriber, _ = full_stack

    # Start subscriber
    subscriber_task = asyncio.create_task(subscriber.run())
    await asyncio.sleep(0.1)

    base_time = datetime.utcnow()

    # Publish snapshots over a time range
    for i in range(10):
        snapshot = {
            "device_id": "SENSOR_1",
            "model": "SENSOR",
            "slave_id": "1",
            "type": "Sensor",
            "sampling_ts": base_time - timedelta(minutes=i),
            "values": {
                "temperature": 25.0 + i * 0.5,
                "humidity": 60.0 - i * 0.3,
            },
        }
        await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, snapshot)

    # Wait for all to be processed
    await asyncio.sleep(0.5)

    # Query time range (last 5 minutes)
    start_time = base_time - timedelta(minutes=5)
    end_time = base_time

    snapshots = await repository.get_time_range("SENSOR_1", start_time, end_time)

    # Should have 6 snapshots (0, 1, 2, 3, 4, 5 minutes ago)
    assert len(snapshots) == 6

    # Verify time ordering (ascending)
    for i in range(len(snapshots) - 1):
        assert snapshots[i]["sampling_ts"] <= snapshots[i + 1]["sampling_ts"]

    # Cleanup
    subscriber_task.cancel()
    try:
        await subscriber_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_parameter_history_integration(full_stack):
    """Test querying specific parameter history."""
    pubsub, repository, subscriber, _ = full_stack

    # Start subscriber
    subscriber_task = asyncio.create_task(subscriber.run())
    await asyncio.sleep(0.1)

    base_time = datetime.utcnow()

    # Publish snapshots with varying temperature
    for i in range(5):
        snapshot = {
            "device_id": "SENSOR_2",
            "model": "SENSOR",
            "slave_id": "2",
            "type": "Sensor",
            "sampling_ts": base_time - timedelta(minutes=i),
            "values": {
                "temperature": 20.0 + i * 2.0,
                "pressure": 1013.0 + i,
            },
        }
        await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, snapshot)

    # Wait for processing
    await asyncio.sleep(0.5)

    # Query temperature history
    start_time = base_time - timedelta(minutes=10)
    end_time = base_time

    temp_history = await repository.get_parameter_history(
        "SENSOR_2", "temperature", start_time, end_time
    )

    assert len(temp_history) == 5

    # Verify values
    temps = [record["value"] for record in temp_history]
    assert min(temps) == 20.0
    assert max(temps) == 28.0

    # Cleanup
    subscriber_task.cancel()
    try:
        await subscriber_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_online_offline_detection_integration(full_stack):
    """Test online/offline status detection in full flow."""
    pubsub, repository, subscriber, _ = full_stack

    # Start subscriber
    subscriber_task = asyncio.create_task(subscriber.run())
    await asyncio.sleep(0.1)

    # Publish online snapshot (normal values)
    online_snapshot = {
        "device_id": "DEVICE_ONLINE",
        "model": "TEST",
        "slave_id": "1",
        "type": "Sensor",
        "sampling_ts": datetime.utcnow(),
        "values": {"temp": 25.0, "humidity": 60.0},
    }
    await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, online_snapshot)

    # Publish offline snapshot (all -1 values)
    offline_snapshot = {
        "device_id": "DEVICE_OFFLINE",
        "model": "TEST",
        "slave_id": "2",
        "type": "Sensor",
        "sampling_ts": datetime.utcnow(),
        "values": {"temp": -1, "humidity": -1},
    }
    await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, offline_snapshot)

    # Wait for processing
    await asyncio.sleep(0.3)

    # Verify online status
    online_data = await repository.get_latest_by_device("DEVICE_ONLINE", limit=1)
    assert len(online_data) == 1
    assert online_data[0]["is_online"] == 1

    # Verify offline status
    offline_data = await repository.get_latest_by_device("DEVICE_OFFLINE", limit=1)
    assert len(offline_data) == 1
    assert offline_data[0]["is_online"] == 0

    # Cleanup
    subscriber_task.cancel()
    try:
        await subscriber_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_database_stats_integration(full_stack, test_db_path):
    """Test database statistics in full flow."""
    pubsub, repository, subscriber, _ = full_stack

    # Start subscriber
    subscriber_task = asyncio.create_task(subscriber.run())
    await asyncio.sleep(0.1)

    # Publish some snapshots
    for i in range(10):
        snapshot = {
            "device_id": f"DEVICE_{i % 3}",  # 3 different devices
            "model": "TEST",
            "slave_id": str(i),
            "type": "Sensor",
            "sampling_ts": datetime.utcnow(),
            "values": {"value": float(i)},
        }
        await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, snapshot)

    # Wait for processing
    await asyncio.sleep(0.5)

    # Get stats
    stats = await repository.get_db_stats(test_db_path)

    assert stats["total_count"] == 10
    assert stats["earliest_ts"] is not None
    assert stats["latest_ts"] is not None
    assert stats["file_size_mb"] > 0

    # Cleanup
    subscriber_task.cancel()
    try:
        await subscriber_task
    except asyncio.CancelledError:
        pass
