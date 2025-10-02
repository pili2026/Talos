from device_manager import AsyncDeviceManager
from schema.sender_schema import SenderSchema
from sender.legacy.legacy_handler import LegacySnapshotHandler
from sender.legacy.legacy_sender import LegacySenderAdapter
from util.config_manager import ConfigManager
from util.pubsub.base import PubSub
from util.pubsub.subscriber.sender_subscriber import SenderSubscriber


def build_sender_subscriber(
    pubsub: PubSub, sender_config_path: str, async_device_manager: AsyncDeviceManager, series_number: int
) -> tuple[LegacySenderAdapter, SenderSubscriber]:
    raw = ConfigManager.load_yaml_file(sender_config_path)

    sender_schema = SenderSchema.model_validate(raw)
    sender_schema.ensure_paths()

    legacy_sender = LegacySenderAdapter(
        sender_config_schema=sender_schema, device_manager=async_device_manager, series_number=series_number
    )
    legacy_handler = LegacySnapshotHandler(legacy_sender)
    return legacy_sender, SenderSubscriber(pubsub, [legacy_handler])


async def init_sender(legacy_sender: LegacySenderAdapter) -> None:
    await legacy_sender.start()
