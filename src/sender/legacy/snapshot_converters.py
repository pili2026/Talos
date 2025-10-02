import logging
import re

from model.enum.equipment_enum import EquipmentType
from util.device_id_policy import DeviceIdPolicy, get_policy

logger = logging.getLogger("SnapshotConverter")


def convert_di_module_snapshot(gateway_id: str, slave_id: str, snapshot: dict[str, str]) -> list[dict]:
    result = []
    # TODO: Range need to refactor
    for i in range(1, 17):  # pins 1..16 → idx = i-1 (zero-based)
        key = f"DIn{i:02d}"
        if key not in snapshot:
            continue
        try:
            relay = int(float(snapshot[key]))
        except Exception:
            continue

        policy: DeviceIdPolicy = get_policy()
        device_id = policy.build_device_id(
            gateway_id=gateway_id, slave_id=slave_id, idx=i - 1, eq_suffix=EquipmentType.SR
        )  # ← unified generation
        data = {
            "Relay0": relay,
            "Relay1": 0,
            "MCStatus0": int(float(snapshot.get("DOut01", "0"))),
            "MCStatus1": int(float(snapshot.get("DOut02", "0"))),
            "ByPass": int(float(snapshot.get("ByPass", "0"))),
        }
        result.append({"DeviceID": device_id, "Data": data})

    return result


def convert_inverter_snapshot(gateway_id: str, slave_id: str, snapshot: dict[str, str]) -> list[dict]:
    field_map = {
        "KWH": ("kwh", float),
        "VOLTAGE": ("voltage", float),
        "CURRENT": ("current", float),
        "KW": ("kw", float),
        "HZ": ("hz", float),
        "ERROR": ("error", int),
        "ALERT": ("alert", int),
        "INVSTATUS": ("invstatus", int),
        "RW_HZ": ("set_hz", int),
        "RW_ON_OFF": ("on_off", int),
    }

    policy: DeviceIdPolicy = get_policy()
    device_id = policy.build_device_id(
        gateway_id=gateway_id, slave_id=slave_id, idx=0, eq_suffix=EquipmentType.CI
    )  # ← TODO:idx=0
    data = {}
    for raw_key, (target_key, caster) in field_map.items():
        val = snapshot.get(raw_key)
        if val is None:
            continue
        try:
            data[target_key] = caster(float(val))
        except Exception:
            pass

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
