# FIXME Need to Refactor
import logging
from typing import Any

from core.model.device_constant import DEFAULT_MISSING_VALUE, INVERTER_OFFLINE_PROBE_KEYS, INVERTER_STATUS_OFFLINE_CODE
from core.sender.legacy.converter_registry import CONVERTER_MAP
from device_manager import AsyncDeviceManager

logger = logging.getLogger("LegacyFormatAdapter")


def is_default_missing_value(value: Any) -> bool:
    """Return True if value equals the system default missing sentinel (-1)."""
    return isinstance(value, (int, float)) and value == DEFAULT_MISSING_VALUE


def infer_inverter_offline_by_probes(values: dict[str, Any]) -> bool:
    """
    Offline if:
      - ≥3 of probe keys are missing, OR
      - INVSTATUS, HZ and RW_ON_OFF are all missing.
    """
    majority_missing = sum(1 for k in INVERTER_OFFLINE_PROBE_KEYS if is_default_missing_value(values.get(k))) >= 3
    core_missing = (
        is_default_missing_value(values.get("INVSTATUS"))
        and is_default_missing_value(values.get("HZ"))
        and is_default_missing_value(values.get("RW_ON_OFF"))
    )
    return majority_missing or core_missing


def coerce_to_non_negative_int(value: Any, default: int = 0) -> int:
    """Convert to non-negative int; return default on invalid or negative."""
    try:
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("ascii", errors="ignore")
        int_value = int(value)
        return int_value if int_value >= 0 else default
    except Exception:
        return default


def set_inverter_status_code(values: dict[str, Any], code: int) -> None:
    """Sync common key names to avoid case inconsistency."""
    for key in ("INVSTATUS", "InverterStatus", "invstatus"):
        values[key] = code


def convert_snapshot_to_legacy_payload(
    gateway_id: str, snapshot: dict[str, Any], device_manager: AsyncDeviceManager
) -> list[dict]:
    """
    Convert one device snapshot into legacy payload items.

    Rules:
    - Keep continuous missing values as -1.
    - For inverter:
        * If inferred offline → set invstatus=9
        * Coerce ERROR/ALERT/RW_ON_OFF to non-negative ints
    - Delegate to converter functions by device_type.
    """
    try:
        device_type: str | None = snapshot.get("type")
        model: str | None = snapshot.get("model")
        slave_id: str | int | None = snapshot.get("slave_id")

        if not device_type or slave_id is None:
            logger.debug("[LegacyFormat] Skip: missing device_type or slave_id")
            return []

        # Shallow copy to avoid polluting the upstream snapshot
        values: dict[str, Any] = dict(snapshot.get("values") or {})

        # Preprocess by type
        if device_type == "inverter":
            looks_offline = values.get("INVSTATUS") == DEFAULT_MISSING_VALUE or infer_inverter_offline_by_probes(values)
            if looks_offline:
                set_inverter_status_code(values, INVERTER_STATUS_OFFLINE_CODE)
            for key in ("ERROR", "ALERT", "RW_ON_OFF"):
                if key in values:
                    values[key] = coerce_to_non_negative_int(values[key], default=0)

        converter_fn = CONVERTER_MAP.get(device_type)
        if not converter_fn:
            logger.debug(f"[LegacyFormat] Skip unsupported type: {device_type}")
            return []

        # Dispatch by type
        match device_type:
            case "ai_module":
                device = device_manager.get_device_by_model_and_slave_id(model, str(slave_id))
                if not device:
                    logger.warning(f"[LegacyFormat] Cannot find device: {model}_{slave_id}")
                    return []
                return converter_fn(
                    gateway_id=gateway_id,
                    slave_id=slave_id,
                    snapshot=values,
                    pin_type_map=device.pin_type_map,
                )
            case "di_module" | "sensor":
                return converter_fn(
                    gateway_id=gateway_id,
                    slave_id=slave_id,
                    snapshot=values,
                    model=model,
                )
            case _:
                # Default
                return converter_fn(gateway_id, slave_id, values)

    except Exception as e:
        logger.warning(f"[LegacyFormat] Error converting snapshot: {e}")
        return []
