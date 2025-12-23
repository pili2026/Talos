from core.executor.control_executor import ControlExecutor
from core.schema.constraint_schema import ConstraintConfigSchema
from core.util.device_health_manager import DeviceHealthManager
from core.util.pubsub.base import PubSub
from core.util.pubsub.subscriber.initialization_subscriber import InitializationSubscriber
from device_manager import AsyncDeviceManager


def build_initialization_subscriber(
    pubsub: PubSub,
    async_device_manager: AsyncDeviceManager,
    constraint_schema: ConstraintConfigSchema,
    health_manager: DeviceHealthManager | None = None,
) -> InitializationSubscriber:
    executor = ControlExecutor(async_device_manager, health_manager)

    return InitializationSubscriber(
        pubsub=pubsub,
        executor=executor,
        constraint_schema=constraint_schema,
        health_manager=health_manager,
        init_priority=50,
    )
