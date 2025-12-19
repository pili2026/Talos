"""
Integration tests simulating Talos offline device scenarios.

This test simulates the real-world scenario where:
- Multiple devices are being monitored
- Some devices are offline (timeout)
- Snapshot storage subscriber is slow (disk I/O)
- System should maintain stable monitoring cycle

Run with:
    pytest test_talos_offline_scenario.py -v -s
"""

import asyncio
import time
from collections import defaultdict
from typing import Any

import pytest

from core.model.topic_policy import DropPolicyEnum
from core.util.pubsub.in_memory_pubsub import InMemoryPubSub
from core.util.pubsub.pubsub_topic import PubSubTopic


class MockDevice:
    """Mock device for testing"""

    def __init__(self, model: str, slave_id: int, is_online: bool = True, read_delay: float = 0.1):
        self.model = model
        self.slave_id = slave_id
        self.is_online = is_online
        self.read_delay = read_delay
        self.read_count = 0

    async def read_all(self) -> dict[str, Any]:
        """Simulate device read with configurable delay and online status"""
        self.read_count += 1

        if not self.is_online:
            # Simulate timeout
            await asyncio.sleep(3.0)
            raise TimeoutError(f"Device {self.model}_{self.slave_id} offline")

        await asyncio.sleep(self.read_delay)
        return {
            "RO_TEMP": 25.5 + self.slave_id,
            "RO_HZ": 50.0,
            "RO_CURRENT": 10.5,
        }


class TestTalosOfflineScenario:
    """Test Talos behavior with offline devices"""

    @pytest.mark.asyncio
    async def test_monitor_cycle_stability_with_offline_devices(self):
        """
        Test that monitor maintains stable cycle time even with offline devices.

        Scenario:
        - 10 devices total
        - 3 devices are offline (3s timeout each)
        - Without optimization: 9s blocked on offline devices per cycle
        - With optimization (fast-skip): <1s per cycle
        """

        # Setup
        pubsub = InMemoryPubSub()
        pubsub.set_topic_policy(PubSubTopic.DEVICE_SNAPSHOT, queue_maxsize=100, drop_policy=DropPolicyEnum.DROP_OLDEST)

        # Create devices: 7 online, 3 offline
        devices = []
        for i in range(7):
            devices.append(MockDevice("VFD", i, is_online=True, read_delay=0.05))

        for i in range(7, 10):
            devices.append(MockDevice("VFD", i, is_online=False))

        # Mock health manager
        health_status = defaultdict(lambda: True)  # All healthy initially

        # Simulate monitor cycle
        async def monitor_cycle(use_health_check: bool = False):
            """Simulate one monitor cycle"""
            snapshots = []

            for device in devices:
                device_id = f"{device.model}_{device.slave_id}"

                # Fast-skip if marked unhealthy (optimization)
                if use_health_check and not health_status[device_id]:
                    # Create offline snapshot without reading
                    snapshots.append(
                        {
                            "device_id": device_id,
                            "is_online": False,
                            "values": {},
                        }
                    )
                    continue

                # Try to read
                try:
                    values = await asyncio.wait_for(device.read_all(), timeout=3.0)
                    snapshots.append(
                        {
                            "device_id": device_id,
                            "is_online": True,
                            "values": values,
                        }
                    )
                    health_status[device_id] = True
                except (TimeoutError, asyncio.TimeoutError):
                    snapshots.append(
                        {
                            "device_id": device_id,
                            "is_online": False,
                            "values": {},
                        }
                    )
                    health_status[device_id] = False

            # Publish snapshots
            for snap in snapshots:
                await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, snap)

            return snapshots

        # Test WITHOUT health check (baseline - slow)
        print("\n" + "=" * 80)
        print("Test 1: WITHOUT health check (baseline)")
        print("=" * 80)

        start = time.time()
        result1 = await monitor_cycle(use_health_check=False)
        elapsed1 = time.time() - start

        print(f"First cycle: {elapsed1:.2f}s (includes 3 offline device timeouts)")
        assert elapsed1 > 9.0  # Should take >9s due to 3x3s timeouts
        assert len(result1) == 10
        assert sum(1 for s in result1 if s["is_online"]) == 7

        # Test WITH health check (optimized - fast)
        print("\n" + "=" * 80)
        print("Test 2: WITH health check (optimized)")
        print("=" * 80)

        start = time.time()
        result2 = await monitor_cycle(use_health_check=True)
        elapsed2 = time.time() - start

        print(f"Second cycle: {elapsed2:.2f}s (offline devices fast-skipped)")
        assert elapsed2 < 1.0  # Should be fast - only online devices read
        assert len(result2) == 10
        assert sum(1 for s in result2 if s["is_online"]) == 7

        print(f"\n✓ Performance improvement: {elapsed1/elapsed2:.1f}x faster")

    @pytest.mark.asyncio
    async def test_pubsub_non_blocking_with_slow_subscriber(self):
        """
        Test that PubSub doesn't block monitor even with slow subscribers.

        Scenario:
        - Monitor publishes snapshots rapidly
        - Snapshot storage subscriber is slow (disk I/O)
        - Monitor should not be blocked by slow subscriber
        """
        pubsub = InMemoryPubSub()
        pubsub.set_topic_policy(PubSubTopic.DEVICE_SNAPSHOT, queue_maxsize=50, drop_policy=DropPolicyEnum.DROP_OLDEST)

        slow_subscriber_received = []
        fast_monitor_published = []

        # Slow subscriber (simulating disk I/O)
        async def slow_snapshot_saver():
            async for snapshot in pubsub.subscribe(PubSubTopic.DEVICE_SNAPSHOT):
                await asyncio.sleep(0.1)  # Simulate slow disk write
                slow_subscriber_received.append(snapshot)
                if len(slow_subscriber_received) >= 20:
                    break

        # Fast monitor
        async def fast_monitor():
            for i in range(100):
                snapshot = {"device_id": f"VFD_{i % 10}", "value": i}
                await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, snapshot)
                fast_monitor_published.append(snapshot)
                await asyncio.sleep(0.01)  # Simulate fast monitoring

        # Run both
        subscriber_task = asyncio.create_task(slow_snapshot_saver())
        await asyncio.sleep(0.05)  # Let subscriber start

        start = time.time()
        await fast_monitor()
        monitor_elapsed = time.time() - start

        await subscriber_task

        print("\n" + "=" * 80)
        print("PubSub Non-Blocking Test Results")
        print("=" * 80)
        print(f"Monitor published: {len(fast_monitor_published)} snapshots in {monitor_elapsed:.2f}s")
        print(f"Slow subscriber received: {len(slow_subscriber_received)} snapshots")
        print(f"Dropped: {pubsub.get_dropped_count(PubSubTopic.DEVICE_SNAPSHOT)}")

        # Monitor should complete quickly (not blocked by slow subscriber)
        assert monitor_elapsed < 2.5  # Should be ~1s (100 * 0.01s)

        # Subscriber should receive subset (not all due to queue limit)
        assert len(slow_subscriber_received) < len(fast_monitor_published)

        # Should have some drops
        assert pubsub.get_dropped_count(PubSubTopic.DEVICE_SNAPSHOT) > 0

        print("\n✓ Monitor not blocked by slow subscriber")
        print("✓ Queue overflow handled gracefully")

    @pytest.mark.asyncio
    async def test_realistic_talos_scenario(self):
        """
        Test realistic Talos scenario with mixed conditions.

        Scenario:
        - 20 devices (simulating real deployment)
        - 5 devices offline
        - Monitor interval: 1s
        - Multiple subscribers with different speeds
        - System should maintain stable operation
        """
        pubsub = InMemoryPubSub()

        # Configure topics
        pubsub.set_topic_policy(PubSubTopic.DEVICE_SNAPSHOT, queue_maxsize=200, drop_policy=DropPolicyEnum.DROP_OLDEST)

        # Create devices
        devices = []
        for i in range(15):
            devices.append(MockDevice("VFD", i, is_online=True, read_delay=0.05))
        for i in range(15, 20):
            devices.append(MockDevice("VFD", i, is_online=False))

        health_status = defaultdict(lambda: True)

        # Stats
        stats = {
            "cycles_completed": 0,
            "snapshots_published": 0,
            "fast_subscriber_received": 0,
            "slow_subscriber_received": 0,
        }

        # Fast subscriber (alert system)
        async def fast_alert_subscriber():
            async for _ in pubsub.subscribe(PubSubTopic.DEVICE_SNAPSHOT):
                stats["fast_subscriber_received"] += 1
                await asyncio.sleep(0.001)  # Very fast processing

        # Slow subscriber (snapshot storage)
        async def slow_storage_subscriber():
            async for _ in pubsub.subscribe(PubSubTopic.DEVICE_SNAPSHOT):
                stats["slow_subscriber_received"] += 1
                await asyncio.sleep(0.05)  # Simulate disk I/O

        # Monitor loop
        async def monitor_loop(cycles: int = 5):
            for _ in range(cycles):
                cycle_start = time.time()

                # Read all devices with health-based fast-skip
                for device in devices:
                    device_id = f"{device.model}_{device.slave_id}"

                    if not health_status[device_id]:
                        # Fast-skip offline devices
                        snapshot = {"device_id": device_id, "is_online": False}
                    else:
                        try:
                            values = await asyncio.wait_for(device.read_all(), timeout=0.5)
                            snapshot = {"device_id": device_id, "is_online": True, "values": values}
                            health_status[device_id] = True
                        except (TimeoutError, asyncio.TimeoutError):
                            snapshot = {"device_id": device_id, "is_online": False}
                            health_status[device_id] = False

                    await pubsub.publish(PubSubTopic.DEVICE_SNAPSHOT, snapshot)
                    stats["snapshots_published"] += 1

                cycle_elapsed = time.time() - cycle_start
                stats["cycles_completed"] += 1

                # Maintain 1s interval
                sleep_time = max(0, 1.0 - cycle_elapsed)
                await asyncio.sleep(sleep_time)

                print(
                    f"Cycle {stats['cycles_completed']}: {cycle_elapsed:.3f}s "
                    f"(published={stats['snapshots_published']}, "
                    f"dropped={pubsub.get_dropped_count(PubSubTopic.DEVICE_SNAPSHOT)})"
                )

        # Run test
        print("\n" + "=" * 80)
        print("Realistic Talos Scenario Test")
        print("=" * 80)
        print("Devices: 20 (15 online, 5 offline)")
        print("Monitor interval: 1s")
        print("Subscribers: 2 (fast alert, slow storage)")
        print("=" * 80)

        fast_task = asyncio.create_task(fast_alert_subscriber())
        slow_task = asyncio.create_task(slow_storage_subscriber())
        await asyncio.sleep(0.05)

        start = time.time()
        await monitor_loop(cycles=5)
        total_elapsed = time.time() - start

        # Stop subscribers
        fast_task.cancel()
        slow_task.cancel()
        try:
            await asyncio.gather(fast_task, slow_task)
        except asyncio.CancelledError:
            pass

        print("\n" + "=" * 80)
        print("Test Results")
        print("=" * 80)
        print(f"Total elapsed: {total_elapsed:.2f}s for {stats['cycles_completed']} cycles")
        print(f"Avg cycle time: {total_elapsed / stats['cycles_completed']:.3f}s")
        print(f"Snapshots published: {stats['snapshots_published']}")
        print(f"Fast subscriber received: {stats['fast_subscriber_received']}")
        print(f"Slow subscriber received: {stats['slow_subscriber_received']}")
        print(f"Dropped: {pubsub.get_dropped_count(PubSubTopic.DEVICE_SNAPSHOT)}")

        # Assertions
        assert stats["cycles_completed"] == 5
        assert stats["snapshots_published"] == 100  # 20 devices × 5 cycles

        # Monitor should maintain stable cycle time (~1s per cycle)
        avg_cycle_time = total_elapsed / stats["cycles_completed"]
        assert avg_cycle_time < 1.5, f"Cycle time too slow: {avg_cycle_time:.2f}s"

        print("\n✓ System maintains stable operation under realistic load")
        print(f"✓ Cycle time stable: {avg_cycle_time:.3f}s")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
