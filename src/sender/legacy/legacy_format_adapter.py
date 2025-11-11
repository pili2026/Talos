import logging

from device_manager import AsyncDeviceManager
from model.device_constant import (
    DEFAULT_MISSING_VALUE,
    INVERTER_OFFLINE_PROBE_KEYS,
    INVERTER_STATUS_OFFLINE_CODE,
)
from sender.legacy.converter_registry import CONVERTER_MAP

logger = logging.getLogger("LegacyFormatAdapter")


def is_missing_value(value) -> bool:
    """Missing value: equals -1 (int or float)."""
    return isinstance(value, (int, float)) and value == DEFAULT_MISSING_VALUE


def infer_inverter_offline_by_probes(values: dict) -> bool:
    """
    Infer offline status using multiple probes:
      - At least three of the five key metrics are missing, OR
      - INVSTATUS, HZ, and RW_ON_OFF are all missing.
    """
    majority_probes_missing = sum(1 for k in INVERTER_OFFLINE_PROBE_KEYS if is_missing_value(values.get(k))) >= 3
    core_fields_missing = (
        is_missing_value(values.get("INVSTATUS"))
        and is_missing_value(values.get("HZ"))
        and is_missing_value(values.get("RW_ON_OFF"))
    )
    return majority_probes_missing or core_fields_missing


def coerce_non_negative_int(value, default: int = 0) -> int:
    """Convert input to a non-negative integer; return default if invalid or negative."""
    try:
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("ascii", errors="ignore")
        int_value = int(value)
        return int_value if int_value >= 0 else default
    except Exception:
        return default


def set_inverter_status_code(values: dict, code: int) -> None:
    """Sync common key names to avoid case inconsistency."""
    for key in ("INVSTATUS", "InverterStatus", "invstatus"):
        values[key] = code


def convert_snapshot_to_legacy_payload(
    gateway_id: str, snapshot: dict, device_manager: AsyncDeviceManager
) -> list[dict]:
    """
    Convert a single device snapshot into a legacy cloud payload fragment.
    - Continuous values: missing values remain -1 (int)
    - Inverter: if inferred offline → set invstatus=9,
      and force other status fields into non-negative integers
    """
    try:
        device_type: str = snapshot.get("type")
        model: str = snapshot.get("model")
        slave_id: str = snapshot.get("slave_id")
        # Shallow copy to avoid polluting upstream snapshot
        values: dict = dict(snapshot.get("values") or {})

        converter_fn = CONVERTER_MAP.get(device_type)
        if not converter_fn:
            logger.debug(f"[LegacyFormat] Skip unsupported type: {device_type}")
            return []

        # Special handling for inverter:
        # infer offline → set invstatus=9;
        # ensure status fields are non-negative
        if device_type == "inverter":
            looks_offline: bool = values.get("INVSTATUS") == DEFAULT_MISSING_VALUE or infer_inverter_offline_by_probes(
                values
            )
            if looks_offline:
                set_inverter_status_code(values, INVERTER_STATUS_OFFLINE_CODE)
            for key in ("ERROR", "ALERT", "RW_ON_OFF"):
                if key in values:
                    values[key] = coerce_non_negative_int(values[key], default=0)

        # Special handling for AI module: needs pin_type_map
        if device_type == "ai_module":
            device = device_manager.get_device_by_model_and_slave_id(model, slave_id)
            if not device:
                logger.warning(f"[LegacyFormat] Cannot find device: {model}_{slave_id}")
                return []
            return converter_fn(
                gateway_id=gateway_id,
                slave_id=slave_id,
                snapshot=values,
                pin_type_map=device.pin_type_map,
            )

        # Special handling for DI module: needs model for DOut mapping
        if device_type == "di_module":
            return converter_fn(
                gateway_id=gateway_id,
                slave_id=slave_id,
                snapshot=values,
                model=model,
            )

        # Special handling for sensor: needs model for routing to specific converter
        if device_type == "sensor":
            return converter_fn(
                gateway_id=gateway_id,
                slave_id=slave_id,
                snapshot=values,
                model=model,
            )

        # Default: standard 3-argument call
        return converter_fn(gateway_id, slave_id, values)

    except Exception as e:
        logger.warning(f"[LegacyFormat] Error converting snapshot: {e}")
        return []
