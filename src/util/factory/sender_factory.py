from device_manager import AsyncDeviceManager
from model.sender_model import SenderModel
from sender.legacy.legacy_handler import LegacySnapshotHandler
from sender.legacy.legacy_sender import LegacySenderAdapter
from util.config_manager import ConfigManager
from util.pubsub.base import PubSub
from util.pubsub.subscriber.sender_subscriber import SenderSubscriber


def _pick_sender_root(cfg: dict) -> dict:
    """
    Support two YAML styles:
    A) Old: all fields at the root (gateway_id/resend_dir/cloud/..., plus sender: flags)
    B) New: everything wrapped under sender: {...}
    Preference is A; if A is missing required keys, then try B.
    """
    # Check A: top-level has required keys
    required = {"gateway_id", "resend_dir", "cloud"}
    if required.issubset(cfg.keys()):
        return cfg

    # Check B: "sender" node contains required keys
    inner: dict = cfg.get("sender")
    if isinstance(inner, dict) and required.issubset(inner.keys()):
        return inner

    # Neither → return the original cfg and let Pydantic raise a clear error
    return cfg


def build_sender_subscriber(
    pubsub: PubSub, sender_config_path: str, async_device_manager: AsyncDeviceManager
) -> tuple[LegacySenderAdapter, SenderSubscriber]:
    raw = ConfigManager.load_yaml_file(sender_config_path)
    sender_cfg = _pick_sender_root(raw)

    sender_model = SenderModel.model_validate(sender_cfg)
    sender_model.ensure_paths()

    legacy_sender = LegacySenderAdapter(sender_model, async_device_manager)
    legacy_handler = LegacySnapshotHandler(legacy_sender)
    return legacy_sender, SenderSubscriber(pubsub, [legacy_handler])


async def init_sender(legacy_sender: LegacySenderAdapter) -> None:
    await legacy_sender.start()
