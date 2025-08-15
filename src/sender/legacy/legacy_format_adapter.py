import logging

from device_manager import AsyncDeviceManager
from sender.legacy.converter_registry import CONVERTER_MAP

logger = logging.getLogger("LegacyFormatAdapter")


def convert_snapshot_to_legacy_payload(
    gateway_id: str, snapshot: dict, device_manager: AsyncDeviceManager
) -> list[dict]:
    try:
        device_type: str = snapshot.get("type")
        model: str = snapshot.get("model")
        slave_id: str = str(snapshot.get("slave_id"))
        values: dict = snapshot.get("values")

        # FIXME: AI need to fix
        converter = CONVERTER_MAP.get(device_type)
        if not converter:
            logger.debug(f"[LegacyFormat] Skip unsupported type: {device_type}")
            return []

        if device_type == "ai_module":
            device = device_manager.get_device_by_model_and_slave_id(model, slave_id)
            if not device:
                logger.warning(f"[LegacyFormat] Cannot find device: {model}_{slave_id}")
                return []

            return converter(
                gateway_id=gateway_id,
                slave_id=int(slave_id),
                snapshot=values,
                pin_type_map=device.pin_type_map,
            )

        return converter(gateway_id, int(slave_id), values)

    except Exception as e:
        logger.warning(f"[LegacyFormat] Error converting snapshot: {e}")
        return []
