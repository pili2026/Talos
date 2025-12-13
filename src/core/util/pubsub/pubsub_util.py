"""
Improved drop metrics loop for main_with_api.py

Replace the existing _pubsub_drop_metrics_loop function with this version.
"""

import asyncio
import logging

from core.model.topic_policy import DropPolicyEnum, TopicPolicyModel
from core.util.pubsub.in_memory_pubsub import InMemoryPubSub
from core.util.pubsub.pubsub_topic import PubSubTopic

logger = logging.getLogger(__name__)

PUBSUB_POLICIES: dict[PubSubTopic, TopicPolicyModel] = {
    # Core pipeline
    PubSubTopic.DEVICE_SNAPSHOT: TopicPolicyModel(queue_maxsize=200, drop_policy=DropPolicyEnum.DROP_OLDEST),
    PubSubTopic.SNAPSHOT_ALLOWED: TopicPolicyModel(queue_maxsize=200, drop_policy=DropPolicyEnum.DROP_OLDEST),
    # Event-like topics (usually want larger buffers)
    PubSubTopic.ALERT_WARNING: TopicPolicyModel(queue_maxsize=1000, drop_policy=DropPolicyEnum.DROP_NEWEST),
    PubSubTopic.CONTROL: TopicPolicyModel(queue_maxsize=1000, drop_policy=DropPolicyEnum.DROP_NEWEST),
}


async def pubsub_drop_metrics_loop(pubsub: InMemoryPubSub, topics_to_monitor: list[PubSubTopic]) -> None:
    """
    Monitor and report PubSub queue overflow metrics.

    Args:
        pubsub: InMemoryPubSub instance
        topics_to_monitor: List of topics to monitor for drops
    """
    report_interval_sec = 10
    last_counts: dict[PubSubTopic, int] = {topic: 0 for topic in topics_to_monitor}

    while True:
        try:
            await asyncio.sleep(report_interval_sec)

            dropped_lines: list[str] = []
            has_new_drops = False

            for topic in topics_to_monitor:
                current_dropped = pubsub.get_dropped_count(topic)

                # Check if there are new drops since last check
                new_drops = current_dropped - last_counts.get(topic, 0)

                if new_drops > 0:
                    has_new_drops = True
                    stats = pubsub.get_queue_stats(topic)

                    dropped_lines.append(
                        f"{topic.value}: +{new_drops} dropped "
                        f"(total={current_dropped}, "
                        f"subscribers={stats['subscriber_count']}, "
                        f"queue_sizes={stats['current_queue_sizes']}, "
                        f"policy={stats['drop_policy']})"
                    )

                last_counts[topic] = current_dropped

            if has_new_drops:
                logger.warning(
                    f"\n{'='*80}\n"
                    f"[PubSub] Message drops detected in the last {report_interval_sec}s:\n"
                    f"{chr(10).join('  - ' + line for line in dropped_lines)}\n"
                    f"{'='*80}\n"
                    f"Hints:\n"
                    f"  1. Slow subscribers detected - consider optimizing subscriber processing\n"
                    f"  2. Consider increasing queue_maxsize if drops persist\n"
                    f"  3. Check system I/O performance (disk, network)\n"
                    f"  4. Review subscriber concurrency limits\n"
                    f"{'='*80}"
                )

        except Exception as exc:
            logger.warning(f"[PubSub] Drop metrics loop error: {exc}")
