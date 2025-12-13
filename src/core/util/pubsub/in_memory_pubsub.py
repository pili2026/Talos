import asyncio
import logging
from collections import defaultdict
from typing import Any, AsyncGenerator, DefaultDict

from core.model.topic_policy import DropPolicyEnum, TopicPolicyModel
from core.util.pubsub.base import PubSub
from core.util.pubsub.pubsub_topic import PubSubTopic

logger = logging.getLogger("InMemoryPubSub")


class InMemoryPubSub(PubSub):
    """
    In-memory PubSub with per-subscriber bounded queues.

    Design goals:
    - publish must be non-blocking (put_nowait)
    - overflow behavior is controllable per topic via TopicPolicyModel
    - dropped counts are tracked per topic for observability
    """

    def __init__(self) -> None:
        self._topic_subscribers: DefaultDict[PubSubTopic, list[asyncio.Queue]] = defaultdict(list)
        self._topic_policy: dict[PubSubTopic, TopicPolicyModel] = {}
        self._dropped: DefaultDict[PubSubTopic, int] = defaultdict(int)

    # ----------------------------
    # Policy
    # ----------------------------

    def set_topic_policy(
        self,
        topic: PubSubTopic,
        *,
        queue_maxsize: int = 200,
        drop_policy: DropPolicyEnum = DropPolicyEnum.DROP_OLDEST,
    ) -> None:
        self._topic_policy[topic] = TopicPolicyModel(queue_maxsize=int(queue_maxsize), drop_policy=drop_policy)

    def set_topic_policy_model(self, topic: PubSubTopic, policy: TopicPolicyModel) -> None:
        self._topic_policy[topic] = policy

    def get_dropped_count(self, topic: PubSubTopic) -> int:
        """Get the current dropped message count for a topic."""
        return int(self._dropped.get(topic, 0))

    def reset_dropped_count(self, topic: PubSubTopic | None = None) -> dict[PubSubTopic, int]:
        """
        Reset and return dropped counts.

        Args:
            topic: If specified, reset only this topic. If None, reset all topics.

        Returns:
            Dictionary mapping topics to their dropped counts before reset.
        """
        if topic:
            count = self._dropped.pop(topic, 0)
            return {topic: count}

        counts = dict(self._dropped)
        self._dropped.clear()
        return counts

    def get_queue_stats(self, topic: PubSubTopic) -> dict[str, Any]:
        """
        Get queue statistics for a topic.

        Returns:
            Dictionary with subscriber_count, max_queue_size, current_queue_sizes, etc.
        """
        queues = self._topic_subscribers.get(topic, [])
        policy = self._get_policy(topic)

        return {
            "subscriber_count": len(queues),
            "max_queue_size": policy.queue_maxsize,
            "drop_policy": policy.drop_policy.value,
            "current_queue_sizes": [q.qsize() for q in queues],
            "total_dropped": self.get_dropped_count(topic),
        }

    # ----------------------------
    # PubSub interface
    # ----------------------------

    async def publish(self, topic: PubSubTopic, data: Any) -> None:
        queues = self._topic_subscribers.get(topic)
        if not queues:
            return

        policy = self._get_policy(topic)

        # iterate a shallow copy to avoid list mutation issues
        for queue in list(queues):
            try:
                queue.put_nowait(data)
                continue
            except asyncio.QueueFull:
                # overflow handling
                if policy.drop_policy == DropPolicyEnum.DROP_NEWEST:
                    # drop incoming message
                    self._dropped[topic] += 1
                    continue

                # DROP_OLDEST: remove oldest, then try to add new
                try:
                    _ = queue.get_nowait()
                    queue.put_nowait(data)
                    self._dropped[topic] += 1  # count the dropped old message
                except asyncio.QueueEmpty:
                    # Race condition: queue was emptied by consumer between full check and get
                    # Try one more time to put the new message
                    try:
                        queue.put_nowait(data)
                    except asyncio.QueueFull:
                        # Still full somehow, drop incoming
                        self._dropped[topic] += 1
                except asyncio.QueueFull:
                    # Should not happen (we just removed one item), but handle defensively
                    self._dropped[topic] += 1
                    logger.warning(
                        f"[PubSub] Unexpected QueueFull after get_nowait for topic={topic.value}, " f"dropping message"
                    )

    async def subscribe(self, topic: PubSubTopic) -> AsyncGenerator[Any, None]:
        policy = self._get_policy(topic)
        queue: asyncio.Queue = asyncio.Queue(maxsize=policy.queue_maxsize)
        self._topic_subscribers[topic].append(queue)

        try:
            while True:
                data = await queue.get()
                yield data
        finally:
            # best-effort removal
            subs = self._topic_subscribers.get(topic, [])
            if queue in subs:
                subs.remove(queue)

    async def close(self) -> None:
        self._topic_subscribers.clear()
        self._topic_policy.clear()
        self._dropped.clear()

    def _get_policy(self, topic: PubSubTopic) -> TopicPolicyModel:
        return self._topic_policy.get(topic, TopicPolicyModel())
