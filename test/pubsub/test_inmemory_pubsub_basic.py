import asyncio

import pytest

from core.model.topic_policy import DropPolicyEnum
from core.util.pubsub.in_memory_pubsub import InMemoryPubSub
from core.util.pubsub.pubsub_topic import PubSubTopic


class TestInMemoryPubSubBasic:
    """Basic functionality tests"""

    @pytest.mark.asyncio
    async def test_basic_publish_subscribe(self):
        """Test basic publish/subscribe without overflow"""
        pubsub = InMemoryPubSub()
        received = []

        async def subscriber():
            async for msg in pubsub.subscribe(PubSubTopic.DEVICE_SNAPSHOT):
                received.append(msg)
                if len(received) >= 3:
                    break

        # Start subscriber
        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.01)  # Let subscriber start

        # Publish messages
        for i in range(3):
            await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, i)

        await task
        assert received == [0, 1, 2]
        assert pubsub.get_dropped_count(PubSubTopic.DEVICE_SNAPSHOT) == 0

    @pytest.mark.asyncio
    async def test_no_subscribers(self):
        """Test publishing to topic with no subscribers"""
        pubsub = InMemoryPubSub()

        # Should not raise
        await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, "test")
        assert pubsub.get_dropped_count(PubSubTopic.DEVICE_SNAPSHOT) == 0

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        """Test multiple subscribers receive all messages"""
        pubsub = InMemoryPubSub()
        received_1 = []
        received_2 = []

        async def subscriber_1():
            async for msg in pubsub.subscribe(PubSubTopic.DEVICE_SNAPSHOT):
                received_1.append(msg)
                if len(received_1) >= 3:
                    break

        async def subscriber_2():
            async for msg in pubsub.subscribe(PubSubTopic.DEVICE_SNAPSHOT):
                received_2.append(msg)
                if len(received_2) >= 3:
                    break

        # Start subscribers
        task1 = asyncio.create_task(subscriber_1())
        task2 = asyncio.create_task(subscriber_2())
        await asyncio.sleep(0.01)

        # Publish messages
        for i in range(3):
            await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, i)

        await asyncio.gather(task1, task2)
        assert received_1 == [0, 1, 2]
        assert received_2 == [0, 1, 2]


class TestDropOldestPolicy:
    """Test DROP_OLDEST policy behavior"""

    @pytest.mark.asyncio
    async def test_drop_oldest_basic(self):
        """Test that oldest messages are dropped when queue is full"""
        pubsub = InMemoryPubSub()
        pubsub.set_topic_policy(PubSubTopic.DEVICE_SNAPSHOT, queue_maxsize=3, drop_policy=DropPolicyEnum.DROP_OLDEST)

        received = []

        async def slow_subscriber():
            async for msg in pubsub.subscribe(PubSubTopic.DEVICE_SNAPSHOT):
                await asyncio.sleep(0.05)  # Slow processing
                received.append(msg)
                if len(received) >= 5:
                    break

        # Start subscriber
        task = asyncio.create_task(slow_subscriber())
        await asyncio.sleep(0.01)

        # Rapidly publish 10 messages (faster than subscriber can process)
        for i in range(10):
            await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, i)

        await task

        # Should receive some messages, but not all
        assert len(received) == 5

        # The latest messages should be preserved (due to DROP_OLDEST)
        # Exact sequence depends on timing, but newest messages should be there
        assert 9 in received  # Newest should definitely be there

        # Should have dropped some messages
        dropped = pubsub.get_dropped_count(PubSubTopic.DEVICE_SNAPSHOT)
        assert dropped > 0
        print(f"\nDropped {dropped} messages, received: {received}")

    @pytest.mark.asyncio
    async def test_drop_oldest_preserves_latest(self):
        """Test that DROP_OLDEST preserves the latest messages"""
        pubsub = InMemoryPubSub()
        pubsub.set_topic_policy(PubSubTopic.DEVICE_SNAPSHOT, queue_maxsize=5, drop_policy=DropPolicyEnum.DROP_OLDEST)

        received = []
        should_stop = False

        async def subscriber():
            async for msg in pubsub.subscribe(PubSubTopic.DEVICE_SNAPSHOT):
                if should_stop:
                    break
                # Don't process immediately - let queue fill up
                received.append(msg)

        # Start subscriber but don't let it process yet
        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.01)

        # Fill queue completely
        for i in range(20):
            await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, i)

        # Now let subscriber process
        await asyncio.sleep(0.05)
        should_stop = True
        await asyncio.sleep(0.01)

        # Cancel subscriber
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should have dropped messages
        dropped = pubsub.get_dropped_count(PubSubTopic.DEVICE_SNAPSHOT)
        assert dropped > 0

        # Latest messages should be in received
        assert 19 in received  # The very last message
        print(f"\nReceived messages: {received}")
        print(f"Dropped: {dropped}")


class TestDropNewestPolicy:
    """Test DROP_NEWEST policy behavior"""

    @pytest.mark.asyncio
    async def test_drop_newest_basic(self):
        """Test that newest messages are dropped when queue is full"""
        pubsub = InMemoryPubSub()
        pubsub.set_topic_policy(PubSubTopic.ALERT_WARNING, queue_maxsize=3, drop_policy=DropPolicyEnum.DROP_NEWEST)

        received = []
        should_stop = False

        async def subscriber():
            async for msg in pubsub.subscribe(PubSubTopic.ALERT_WARNING):
                if should_stop:
                    break
                await asyncio.sleep(0.05)
                received.append(msg)

        # Start subscriber
        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.01)

        # Rapidly publish messages
        for i in range(10):
            await pubsub.publish(PubSubTopic.ALERT_WARNING, i)

        # Let some process
        await asyncio.sleep(0.3)
        should_stop = True
        await asyncio.sleep(0.01)

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should have dropped some messages
        dropped = pubsub.get_dropped_count(PubSubTopic.ALERT_WARNING)
        assert dropped > 0

        # First messages should be preserved (DROP_NEWEST drops incoming)
        assert 0 in received
        print(f"\nDropped {dropped} messages, received: {received}")


class TestQueueManagement:
    """Test queue statistics and management"""

    @pytest.mark.asyncio
    async def test_get_queue_stats(self):
        """Test queue statistics reporting"""
        pubsub = InMemoryPubSub()
        pubsub.set_topic_policy(PubSubTopic.DEVICE_SNAPSHOT, queue_maxsize=100, drop_policy=DropPolicyEnum.DROP_OLDEST)

        # Add some subscribers
        async def subscriber():
            async for _ in pubsub.subscribe(PubSubTopic.DEVICE_SNAPSHOT):
                await asyncio.sleep(1)

        task1 = asyncio.create_task(subscriber())
        task2 = asyncio.create_task(subscriber())
        await asyncio.sleep(0.01)

        # Publish some messages
        for i in range(10):
            await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, i)

        stats = pubsub.get_queue_stats(PubSubTopic.DEVICE_SNAPSHOT)

        assert stats["subscriber_count"] == 2
        assert stats["max_queue_size"] == 100
        assert stats["drop_policy"] == "drop_oldest"
        assert len(stats["current_queue_sizes"]) == 2
        assert all(size == 10 for size in stats["current_queue_sizes"])

        # Cleanup
        task1.cancel()
        task2.cancel()
        try:
            await asyncio.gather(task1, task2)
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_reset_dropped_count_single_topic(self):
        """Test resetting dropped count for a single topic"""
        pubsub = InMemoryPubSub()
        pubsub.set_topic_policy(PubSubTopic.DEVICE_SNAPSHOT, queue_maxsize=2, drop_policy=DropPolicyEnum.DROP_OLDEST)

        async def subscriber():
            async for msg in pubsub.subscribe(PubSubTopic.DEVICE_SNAPSHOT):
                await asyncio.sleep(0.1)

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.01)

        # Generate some drops
        for i in range(10):
            await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, i)

        # Should have drops
        assert pubsub.get_dropped_count(PubSubTopic.DEVICE_SNAPSHOT) > 0

        # Reset and get count
        counts = pubsub.reset_dropped_count(PubSubTopic.DEVICE_SNAPSHOT)
        assert PubSubTopic.DEVICE_SNAPSHOT in counts
        assert counts[PubSubTopic.DEVICE_SNAPSHOT] > 0

        # Should be zero after reset
        assert pubsub.get_dropped_count(PubSubTopic.DEVICE_SNAPSHOT) == 0

        # Cleanup
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_reset_dropped_count_all_topics(self):
        """Test resetting dropped count for all topics"""
        pubsub = InMemoryPubSub()

        # Set up two topics with drops
        for topic in [PubSubTopic.DEVICE_SNAPSHOT, PubSubTopic.ALERT_WARNING]:
            pubsub.set_topic_policy(topic, queue_maxsize=2, drop_policy=DropPolicyEnum.DROP_OLDEST)

        async def subscriber(topic):
            async for msg in pubsub.subscribe(topic):
                await asyncio.sleep(0.1)

        task1 = asyncio.create_task(subscriber(PubSubTopic.DEVICE_SNAPSHOT))
        task2 = asyncio.create_task(subscriber(PubSubTopic.ALERT_WARNING))
        await asyncio.sleep(0.01)

        # Generate drops on both topics
        for i in range(10):
            await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, i)
            await pubsub.publish(PubSubTopic.ALERT_WARNING, i)

        # Both should have drops
        assert pubsub.get_dropped_count(PubSubTopic.DEVICE_SNAPSHOT) > 0
        assert pubsub.get_dropped_count(PubSubTopic.ALERT_WARNING) > 0

        # Reset all
        all_counts = pubsub.reset_dropped_count()
        assert len(all_counts) == 2
        assert all(count > 0 for count in all_counts.values())

        # All should be zero
        assert pubsub.get_dropped_count(PubSubTopic.DEVICE_SNAPSHOT) == 0
        assert pubsub.get_dropped_count(PubSubTopic.ALERT_WARNING) == 0

        # Cleanup
        task1.cancel()
        task2.cancel()
        try:
            await asyncio.gather(task1, task2)
        except asyncio.CancelledError:
            pass


class TestEdgeCases:
    """Test edge cases and error handling"""

    @pytest.mark.asyncio
    async def test_subscriber_cleanup_on_exit(self):
        """Test that subscribers are removed when they exit"""
        pubsub = InMemoryPubSub()

        async def subscriber():
            count = 0
            async for msg in pubsub.subscribe(PubSubTopic.DEVICE_SNAPSHOT):
                count += 1
                if count >= 3:
                    break

        # Check initial state
        stats_before = pubsub.get_queue_stats(PubSubTopic.DEVICE_SNAPSHOT)
        assert stats_before["subscriber_count"] == 0

        # Run subscriber
        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.01)

        # Should have one subscriber
        stats_during = pubsub.get_queue_stats(PubSubTopic.DEVICE_SNAPSHOT)
        assert stats_during["subscriber_count"] == 1

        # Send messages
        for i in range(3):
            await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, i)

        await task

        # Subscriber should be removed
        await asyncio.sleep(0.01)
        stats_after = pubsub.get_queue_stats(PubSubTopic.DEVICE_SNAPSHOT)
        assert stats_after["subscriber_count"] == 0

    @pytest.mark.asyncio
    async def test_concurrent_publish_no_race(self):
        """Test concurrent publishing doesn't cause issues"""
        pubsub = InMemoryPubSub()
        pubsub.set_topic_policy(PubSubTopic.DEVICE_SNAPSHOT, queue_maxsize=50, drop_policy=DropPolicyEnum.DROP_OLDEST)

        received = []

        async def subscriber():
            async for msg in pubsub.subscribe(PubSubTopic.DEVICE_SNAPSHOT):
                received.append(msg)
                if len(received) >= 100:
                    break

        # Start subscriber
        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.01)

        # Concurrent publishers
        async def publisher(start, count):
            for i in range(start, start + count):
                await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, i)

        # Run multiple publishers concurrently
        await asyncio.gather(
            publisher(0, 50),
            publisher(50, 50),
        )

        await task

        # Should receive all or most messages
        assert len(received) >= 90  # Allow some drops due to queue size
        print(f"\nReceived {len(received)} out of 100 messages")

    @pytest.mark.asyncio
    async def test_policy_change_before_subscribers(self):
        """Test that policy changes work before subscribers exist"""
        pubsub = InMemoryPubSub()

        # Set policy before any subscribers
        pubsub.set_topic_policy(PubSubTopic.DEVICE_SNAPSHOT, queue_maxsize=10, drop_policy=DropPolicyEnum.DROP_NEWEST)

        stats = pubsub.get_queue_stats(PubSubTopic.DEVICE_SNAPSHOT)
        assert stats["max_queue_size"] == 10
        assert stats["drop_policy"] == "drop_newest"

    @pytest.mark.asyncio
    async def test_close_cleanup(self):
        """Test that close() cleans up properly"""
        pubsub = InMemoryPubSub()
        pubsub.set_topic_policy(PubSubTopic.DEVICE_SNAPSHOT, queue_maxsize=5, drop_policy=DropPolicyEnum.DROP_OLDEST)

        async def subscriber():
            async for _ in pubsub.subscribe(PubSubTopic.DEVICE_SNAPSHOT):
                pass

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.01)

        # Generate some activity
        for i in range(10):
            await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, i)

        # Close
        await pubsub.close()

        # Should be cleaned
        stats = pubsub.get_queue_stats(PubSubTopic.DEVICE_SNAPSHOT)
        assert stats["subscriber_count"] == 0
        assert stats["total_dropped"] == 0

        # Cleanup
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


class TestPerformance:
    """Performance and stress tests"""

    @pytest.mark.asyncio
    async def test_high_throughput(self):
        """Test system behavior under high message throughput"""
        pubsub = InMemoryPubSub()
        pubsub.set_topic_policy(PubSubTopic.DEVICE_SNAPSHOT, queue_maxsize=100, drop_policy=DropPolicyEnum.DROP_OLDEST)

        received_count = 0

        async def fast_subscriber():
            nonlocal received_count
            async for _ in pubsub.subscribe(PubSubTopic.DEVICE_SNAPSHOT):
                received_count += 1
                if received_count >= 1000:
                    break

        task = asyncio.create_task(fast_subscriber())
        await asyncio.sleep(0.01)

        # Publish many messages rapidly
        start = asyncio.get_event_loop().time()
        for i in range(1000):
            await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, i)
        elapsed = asyncio.get_event_loop().time() - start

        await task

        print(f"\nPublished 1000 messages in {elapsed:.3f}s ({1000/elapsed:.0f} msg/s)")
        print(f"Received: {received_count}, Dropped: {pubsub.get_dropped_count(PubSubTopic.DEVICE_SNAPSHOT)}")

        assert received_count >= 900  # Should receive most messages


if __name__ == "__main__":
    # Run with: python test_in_memory_pubsub.py
    pytest.main([__file__, "-v", "-s"])
