"""Unit tests for SnapshotSaverSubscriber."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest
import pytest_asyncio

from repository.snapshot_repository import SnapshotRepository
from util.pubsub.in_memory_pubsub import InMemoryPubSub
from util.pubsub.pubsub_topic import PubSubTopic
from util.pubsub.subscriber.snapshot_saver_subscriber import SnapshotSaverSubscriber


@pytest_asyncio.fixture
async def mock_repository():
    """Create a mock repository."""
    repo = Mock(spec=SnapshotRepository)
    repo.insert_snapshot = AsyncMock()
    return repo


@pytest_asyncio.fixture
async def pubsub():
    """Create a PubSub instance."""
    return InMemoryPubSub()


@pytest_asyncio.fixture
async def subscriber(pubsub, mock_repository):
    """Create SnapshotSaverSubscriber instance."""
    return SnapshotSaverSubscriber(pubsub, mock_repository)


@pytest.fixture
def sample_snapshot():
    """Create a sample snapshot."""
    return {
        "device_id": "A26A_1",
        "model": "A26A",
        "slave_id": "1",
        "type": "Inverter",
        "sampling_ts": datetime.utcnow(),
        "values": {
            "VIn": 220.5,
            "HZ": 60.0,
        },
    }


@pytest.mark.asyncio
async def test_handle_snapshot_success(subscriber, mock_repository, sample_snapshot):
    """Test successful snapshot handling."""
    await subscriber.handle_snapshot(sample_snapshot)

    # Verify repository was called
    mock_repository.insert_snapshot.assert_called_once_with(sample_snapshot)


@pytest.mark.asyncio
async def test_handle_snapshot_error_isolation(subscriber, mock_repository, sample_snapshot):
    """Test that errors are isolated and don't propagate."""
    # Make repository raise an error
    mock_repository.insert_snapshot.side_effect = Exception("Database error")

    # Should not raise exception
    try:
        await subscriber.handle_snapshot(sample_snapshot)
    except Exception as e:
        pytest.fail(f"handle_snapshot should not raise exception, but raised: {e}")


@pytest.mark.asyncio
async def test_run_receives_and_saves_snapshots(pubsub, mock_repository, sample_snapshot):
    """Test that run() subscribes to DEVICE_SNAPSHOT and saves snapshots."""
    subscriber = SnapshotSaverSubscriber(pubsub, mock_repository)

    # Start subscriber in background
    subscriber_task = asyncio.create_task(subscriber.run())

    # Give it time to start subscribing
    await asyncio.sleep(0.1)

    # Publish a snapshot
    await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, sample_snapshot)

    # Give it time to process
    await asyncio.sleep(0.1)

    # Verify snapshot was saved
    assert mock_repository.insert_snapshot.call_count >= 1
    mock_repository.insert_snapshot.assert_called_with(sample_snapshot)

    # Cleanup
    subscriber_task.cancel()
    try:
        await subscriber_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_run_continues_after_error(pubsub, mock_repository, sample_snapshot):
    """Test that subscriber continues processing after an error."""
    subscriber = SnapshotSaverSubscriber(pubsub, mock_repository)

    # First call raises error, second succeeds
    mock_repository.insert_snapshot.side_effect = [
        Exception("First error"),
        None,  # Success
    ]

    # Start subscriber in background
    subscriber_task = asyncio.create_task(subscriber.run())
    await asyncio.sleep(0.1)

    # Publish two snapshots
    snapshot1 = sample_snapshot.copy()
    snapshot1["device_id"] = "DEVICE_1"

    snapshot2 = sample_snapshot.copy()
    snapshot2["device_id"] = "DEVICE_2"

    await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, snapshot1)
    await asyncio.sleep(0.1)

    await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, snapshot2)
    await asyncio.sleep(0.1)

    # Both should have been attempted
    assert mock_repository.insert_snapshot.call_count == 2

    # Cleanup
    subscriber_task.cancel()
    try:
        await subscriber_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_multiple_snapshots_handling(pubsub, mock_repository):
    """Test handling multiple snapshots in sequence."""
    subscriber = SnapshotSaverSubscriber(pubsub, mock_repository)

    # Start subscriber
    subscriber_task = asyncio.create_task(subscriber.run())
    await asyncio.sleep(0.1)

    # Publish multiple snapshots
    for i in range(5):
        snapshot = {
            "device_id": f"DEVICE_{i}",
            "model": "TEST",
            "slave_id": str(i),
            "type": "Sensor",
            "sampling_ts": datetime.utcnow(),
            "values": {"temp": 25.0 + i},
        }
        await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, snapshot)

    # Give time to process all
    await asyncio.sleep(0.5)

    # All should have been saved
    assert mock_repository.insert_snapshot.call_count == 5

    # Cleanup
    subscriber_task.cancel()
    try:
        await subscriber_task
    except asyncio.CancelledError:
        pass
