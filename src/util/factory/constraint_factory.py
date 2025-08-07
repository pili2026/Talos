from evaluator.constraint_evaluator import ConstraintEvaluator
from util.pubsub.base import PubSub
from util.pubsub.subscriber.constraint_evaluator_subscriber import ConstraintSubscriber


def build_constraint_subscriber(pubsub: PubSub) -> ConstraintSubscriber:
    constraint_evaluator = ConstraintEvaluator(pubsub)
    constraint_subscriber = ConstraintSubscriber(pubsub, constraint_evaluator)
    return constraint_subscriber
