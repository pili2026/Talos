import logging
import re

from model.enum.equipment_enum import EquipmentType
from util.converter_invstatus import compute_legacy_invstatus_code, to_int_or_none, u16_to_bit_flags, u16_to_hex
from util.device_id_policy import DeviceIdPolicy, get_policy

logger = logging.getLogger("SnapshotConverter")


def _get_do_state_for_di(snapshot: dict, di_pin_num: int, model: str) -> int:
    """
    Get corresponding DOut state for DIn pin (model-specific).

    Model-specific rules:
    - IMA_C: DInXX.MCStatus0 maps to DOutXX (same pin number)
          DIn01 → DOut01, DIn02 → DOut02
    - Other models: No mapping, returns 0

    Args:
        snapshot: Device snapshot containing DOut values
        di_pin_num: DI pin number (e.g., 1 for DIn01)
        model: Device model name

    Returns:
        DOut value (0 or 1), or 0 if not found/not applicable

    Examples:
        >>> _get_do_state_for_di({"DOut01": "1"}, 1, "IMA_C")
        1
        >>> _get_do_state_for_di({"DOut01": "1"}, 1, "OTHER_MODEL")
        0
        >>> _get_do_state_for_di({}, 1, "IMA_C")
        0
    """
    if model != "IMA_C":
        return 0

    # IMA_C specific: map DInXX to DOutXX
    do_pin_name = f"DOut{di_pin_num:02d}"

    if do_pin_name not in snapshot:
        logger.debug(f"[LegacyFormat] {do_pin_name} not found in snapshot for IMA_C")
        return 0

    try:
        return int(float(snapshot[do_pin_name]))
    except Exception as e:
        logger.warning(
            f"[LegacyFormat] Invalid DOut value for {do_pin_name}: " f"{snapshot.get(do_pin_name)}, error: {e}"
        )
        return 0


def convert_di_module_snapshot(gateway_id: str, slave_id: str, snapshot: dict[str, str], model: str) -> list[dict]:
    """
    Convert Digital Input module to legacy format.

    Each DI pin generates one record with:
    - Relay0: DI pin value (0/1)
    - MCStatus0: Corresponding DO state (model-specific, see _get_do_state_for_di)
    - Relay1, MCStatus1, ByPass: Reserved fields (currently 0)

    Model-specific behavior:
    - IMA_C: MCStatus0 populated from matching DOut pin (DIn01→DOut01, DIn02→DOut02)
    - Others: MCStatus0 = 0 (no DO state tracking)

    Note: This converter only handles Digital Input (DIn) pins.
          Digital Output (DOut) states are NOT uploaded as separate records.
          They are only included as MCStatus0 in DI records for specific models (IMA_C).

          In test environments, DO signals may be wired back to DI pins for monitoring.

    Args:
        gateway_id: Gateway identifier
        slave_id: Device slave ID
        snapshot: Device snapshot containing DIn (and optionally DOut) values
        model: Device model name for model-specific logic

    Returns:
        List of legacy format records, one per DI pin

    Examples:
        >>> snapshot = {"DIn01": "1", "DIn02": "0", "DOut01": "1", "DOut02": "0"}
        >>> result = convert_di_module_snapshot("GW123", "5", snapshot, "IMA_C")
        >>> len(result)
        2
        >>> result[0]["Data"]["Relay0"]  # DIn01 value
        1
        >>> result[0]["Data"]["MCStatus0"]  # DOut01 value
        1
        >>> result[1]["Data"]["Relay0"]  # DIn02 value
        0
        >>> result[1]["Data"]["MCStatus0"]  # DOut02 value
        0
    """
    result = []

    # Dynamically match all DIn pins (DIn01, DIn02, ..., DIn99)
    di_pattern = re.compile(r"^DIn(\d+)$")
    di_pins = []

    for key in snapshot.keys():
        match = di_pattern.match(key)
        if match:
            pin_number = int(match.group(1))
            di_pins.append((pin_number, key))

    # Sort by pin number to ensure consistent order
    di_pins.sort(key=lambda x: x[0])

    if not di_pins:
        logger.debug(f"[LegacyFormat] No DIn pins found in snapshot for {slave_id}")
        return result

    logger.debug(
        f"[LegacyFormat] Found {len(di_pins)} DI pins for {slave_id} (model={model}): " f"{[pin[1] for pin in di_pins]}"
    )

    for idx, (pin_num, pin_name) in enumerate(di_pins):
        try:
            pin_value = int(float(snapshot[pin_name]))
        except Exception as e:
            logger.warning(f"[LegacyFormat] Invalid value for {pin_name}: " f"{snapshot.get(pin_name)}, error: {e}")
            continue

        # Model-specific DO state mapping
        mc_status0 = _get_do_state_for_di(snapshot, pin_num, model)

        policy: DeviceIdPolicy = get_policy()
        device_id = policy.build_device_id(
            gateway_id=gateway_id,
            slave_id=slave_id,
            idx=idx,  # DIn01 → idx=0, DIn02 → idx=1, ...
            eq_suffix=EquipmentType.SR,
        )

        data = {
            "Relay0": pin_value,
            "Relay1": 0,
            "MCStatus0": mc_status0,  # Now populated for IMA_C
            "MCStatus1": 0,
            "ByPass": 0,
        }

        result.append({"DeviceID": device_id, "Data": data})

    return result


def convert_inverter_snapshot(gateway_id: str, slave_id: str, snapshot: dict[str, str]) -> list[dict]:
    """
    Convert inverter snapshot data into the Legacy format.
    - Regular numeric fields are directly cast to the expected type.
    - INVSTATUS: keep raw value, expose debug-friendly fields (hex/bit flags),
      and compute legacy-compatible status code.
    """
    field_map = {
        "KWH": ("kwh", float),
        "VOLTAGE": ("voltage", float),
        "CURRENT": ("current", float),
        "KW": ("kw", float),
        "HZ": ("hz", float),
        "ERROR": ("error", int),
        "ALERT": ("alert", int),
        # "INVSTATUS" handled in a dedicated section (with derived fields)
        "RW_HZ": ("set_hz", int),
        "RW_ON_OFF": ("on_off", int),
    }

    policy: DeviceIdPolicy = get_policy()
    device_id = policy.build_device_id(gateway_id=gateway_id, slave_id=slave_id, idx=0, eq_suffix=EquipmentType.CI)

    data: dict = {}

    # Regular numeric fields
    for raw_key, (target_key, caster) in field_map.items():
        raw_val: str | None = snapshot.get(raw_key)
        if raw_val is None:
            continue
        try:
            data[target_key] = caster(float(raw_val))
        except Exception:
            pass

    # ---- INVSTATUS section: raw + derived fields + compatibility mapping ----
    invstatus_raw: int | None = to_int_or_none(snapshot.get("INVSTATUS"))

    # Debug-friendly / visualization fields (raw, hex, bit-flags)
    data["invstatus_raw_u16"] = invstatus_raw
    data["invstatus_hex"] = u16_to_hex(invstatus_raw)
    data["invstatus_bits"] = u16_to_bit_flags(invstatus_raw)

    # Legacy-compatible status code (%10 rule; negative → 0)
    invstatus_code: int | None = compute_legacy_invstatus_code(invstatus_raw, negative_fallback=0)
    data["invstatus_code"] = invstatus_code

    # Legacy cloud expects field name "invstatus" (required in legacy payload)
    if invstatus_code is not None:
        data["invstatus"] = invstatus_code

    return [{"DeviceID": device_id, "Data": data}] if data else []


def _infer_idx_from_key(key: str) -> int:
    m = re.search(r"(\d+)$", key)  # extract trailing number
    return int(m.group(1)) - 1 if m else 0  # 1-based → 0-based


def convert_ai_module_snapshot(
    gateway_id: str,
    slave_id: int,
    snapshot: dict[str, str],
    pin_type_map: dict[str, str],
) -> list[dict]:
    pin_suffix_map = {"Temp": EquipmentType.ST, "Pressure": EquipmentType.SP}
    result = []

    for key, val in snapshot.items():
        sensor_type = pin_type_map.get(key)
        if not sensor_type:
            continue
        try:
            value = float(val)
        except Exception:
            continue

        idx = _infer_idx_from_key(key)  # ← ensure stable idx
        policy: DeviceIdPolicy = get_policy()
        device_id = policy.build_device_id(
            gateway_id=gateway_id, slave_id=slave_id, idx=idx, eq_suffix=pin_suffix_map.get(sensor_type, "")
        )
        result.append({"DeviceID": device_id, "Data": {sensor_type: value}})

    return result


def convert_flow_meter(gateway_id: str, slave_id: int, values: dict) -> list[dict]:
    policy: DeviceIdPolicy = get_policy()
    device_id = policy.build_device_id(gateway_id=gateway_id, slave_id=slave_id, idx=0, eq_suffix=EquipmentType.SF)
    return [
        {
            "DeviceID": device_id,
            "Data": {
                "flow": round(values.get("FLOW_VALUE", 0.0) * 23.1784214, 4),
                "consumption": int(values.get("FLOW_CONSUMPTION", 0.0) * 23.1784214),
                "revconsumption": int(values.get("FLOW_REVCONSUMPTION", 0.0) * 23.1784214),
                "direction": 65535 if values.get("FLOW_DIRECTION") == -1 else int(values.get("FLOW_DIRECTION", 0)),
            },
        }
    ]


def convert_power_meter_snapshot(gateway_id: str, slave_id: str | int, values: dict[str, str]) -> list[dict]:
    """
    Convert driver snapshot into SE's Data.

    New driver (M1+) already applies all scaling:
      - AverageVoltage/Current, Phase_*_Current already applied index scaling
      - Kw/Kva/Kvar already applied energy_index scaling
      - AveragePowerFactor already multiplied by 0.001
      - Kwh_SUM / Kvarh_SUM already composed from 3 words and scaled (KWh also handles MV mode)

    Therefore we just map fields; no extra scaling.

    Legacy fallback (pre-M1): if Kwh_SUM/Kvarh_SUM are missing, reconstruct them and use energy_index (no MV support).
    """

    def to_int(x):
        try:
            return int(float(x))
        except Exception:
            return 0

    def to_float(x):
        try:
            return float(x)
        except Exception:
            return 0.0

    # --- Direct mapping (no further scaling) ---
    mapped = {
        "AverageVoltage": to_float(values.get("AverageVoltage")),
        "AverageCurrent": to_float(values.get("AverageCurrent")),
        "Phase_A_Current": to_float(values.get("Phase_A_Current")),
        "Phase_B_Current": to_float(values.get("Phase_B_Current")),
        "Phase_C_Current": to_float(values.get("Phase_C_Current")),
        "Kw": to_float(values.get("Kw")),
        "Kva": to_float(values.get("Kva")),
        "Kvar": to_float(values.get("Kvar")),
        "AveragePowerFactor": to_float(values.get("AveragePowerFactor")),
    }

    # Energies: prefer already composed SUM fields (new driver)
    if "Kwh_SUM" in values and "Kvarh_SUM" in values:
        mapped["Kwh"] = to_float(values.get("Kwh_SUM"))
        mapped["Kvarh"] = to_float(values.get("Kvarh_SUM"))
    else:
        # ---- Legacy fallback (only for old driver): estimate with energy_index, without MV handling ----
        ki = to_int(values.get("SCALE_EnergyIndex"))

        k_list = [0.1, 1.0, 10.0, 100.0, 1000.0, 10000.0, 100000.0, 1000000.0]

        # Used only in fallback; for safety use default if index is invalid
        e_mul = (k_list[ki] * 0.001) if 0 <= ki < len(k_list) else 0.001

        def read_3w(prefix: str) -> float:
            w1 = to_int(values.get(f"{prefix}_W1_HI"))
            w2 = to_int(values.get(f"{prefix}_W2_MD"))
            w3 = to_int(values.get(f"{prefix}_W3_LO"))
            return ((w1 << 32) | (w2 << 16) | w3) * e_mul

        mapped["Kwh"] = read_3w("Kwh")
        mapped["Kvarh"] = read_3w("Kvarh")

    # --- Rounding rules (same as your original convention) ---
    round2 = (
        "AverageVoltage",
        "AverageCurrent",
        "Phase_A_Current",
        "Phase_B_Current",
        "Phase_C_Current",
        "Kw",
        "Kva",
        "Kvar",
        "Kwh",
        "Kvarh",
    )
    for k in round2:
        mapped[k] = round(mapped.get(k, 0.0), 2)
    mapped["AveragePowerFactor"] = round(mapped.get("AveragePowerFactor", 0.0), 3)

    # Device ID (reuse your convention)
    policy: DeviceIdPolicy = get_policy()
    device_id: str = policy.build_device_id(gateway_id=gateway_id, slave_id=slave_id, idx=0, eq_suffix=EquipmentType.SE)
    return [{"DeviceID": device_id, "Data": mapped}]
