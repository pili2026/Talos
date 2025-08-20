import logging

from model.enum.equipment_enum import EqType

logger = logging.getLogger("SnapshotConverter")


def convert_di_module_snapshot(gateway_id: str, slave_id: str, snapshot: dict[str, str]) -> list[dict]:
    result = []

    # TODO: Range need to refactor
    for i in range(1, 17):
        key = f"DIn{i:02d}"
        if key not in snapshot:
            continue
        try:
            relay = int(float(snapshot[key]))
        except Exception:
            continue

        suffix = build_device_suffix(slave_id, i - 1) + EqType.SR
        device_id = f"{gateway_id}_{suffix}"

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

    suffix = build_device_suffix(slave_id, 0) + EqType.CI
    device_id = f"{gateway_id}_{suffix}"

    data = {}
    for raw_key, (target_key, caster) in field_map.items():
        val = snapshot.get(raw_key)
        if val is not None:
            try:
                data[target_key] = caster(float(val))
            except Exception:
                continue

    return [{"DeviceID": device_id, "Data": data}] if data else []


def convert_ai_module_snapshot(
    gateway_id: str,
    slave_id: int,
    snapshot: dict[str, str],
    pin_type_map: dict[str, str],
) -> list[dict]:
    pin_suffix_map = {
        "Temp": EqType.ST,
        "Pressure": EqType.SP,
    }

    result = []

    for idx, (key, val) in enumerate(snapshot.items()):
        try:
            value = float(val)
        except Exception:
            continue

        sensor_type = pin_type_map.get(key)
        if not sensor_type:
            continue

        suffix = build_device_suffix(slave_id, idx) + pin_suffix_map.get(sensor_type, "")
        device_id = f"{gateway_id}_{suffix}"

        result.append({"DeviceID": device_id, "Data": {sensor_type: value}})

    return result


def convert_flow_meter(gateway_id: str, slave_id: int, values: dict) -> list[dict]:
    suffix = build_device_suffix(slave_id, 0) + EqType.SF
    device_id = f"{gateway_id}_{suffix}"

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
    Convert the new driver output of the power meter (without PM_ prefix) into SE's Data.
    Required keys:
      - (3-word) Kwh_W1_HI/W2_MD/W3_LO, Kvarh_W1_HI/W2_MD/W3_LO
      - AverageVoltage/Current, Phase_A/B/C_Current
      - Kw/Kva/Kvar, AveragePowerFactor
      - SCALE_VoltageIndex/CurrentIndex/EnergyIndex
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

    # Index → multiplier
    vi = to_int(values.get("SCALE_VoltageIndex"))
    ai = to_int(values.get("SCALE_CurrentIndex"))
    ki = to_int(values.get("SCALE_EnergyIndex"))

    v_list = [0.1, 1.0, 10.0, 100.0]
    a_list = [0.001, 0.010, 0.1]
    k_list = [0.1, 1.0, 10.0, 100.0, 1000.0, 10000.0, 100000.0, 1000000.0]

    v_mul = v_list[vi] if 0 <= vi < len(v_list) else 1.0
    a_mul = a_list[ai] if 0 <= ai < len(a_list) else 0.01
    e_mul = (k_list[ki] * 0.001) if 0 <= ki < len(k_list) else 1.0

    # General measurements
    data = {
        "AverageVoltage": to_float(values.get("AverageVoltage")) * v_mul,
        "AverageCurrent": to_float(values.get("AverageCurrent")) * a_mul,
        "Phase_A_Current": to_float(values.get("Phase_A_Current")) * a_mul,
        "Phase_B_Current": to_float(values.get("Phase_B_Current")) * a_mul,
        "Phase_C_Current": to_float(values.get("Phase_C_Current")) * a_mul,
        "Kw": to_float(values.get("Kw")) * e_mul,
        "Kva": to_float(values.get("Kva")) * e_mul,
        "Kvar": to_float(values.get("Kvar")) * e_mul,
        "AveragePowerFactor": to_float(values.get("AveragePowerFactor")) * 0.001,
    }

    # 3-word (48-bit, big-endian)
    def read_3w(prefix: str) -> float:
        w1 = to_int(values.get(f"{prefix}_W1_HI"))
        w2 = to_int(values.get(f"{prefix}_W2_MD"))
        w3 = to_int(values.get(f"{prefix}_W3_LO"))
        return ((w1 << 32) | (w2 << 16) | w3) * e_mul

    data["Kwh"] = read_3w("Kwh")
    data["Kvarh"] = read_3w("Kvarh")

    # Round according to documentation (PF: 3 decimals, others: 2 decimals; adjustable)
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
        data[k] = round(data.get(k, 0.0), 2)
    data["AveragePowerFactor"] = round(data.get("AveragePowerFactor", 0.0), 3)

    # Device ID (reuse your convention)
    suffix = build_device_suffix(slave_id, 0) + EqType.SE
    device_id = f"{gateway_id}_{suffix}"

    return [{"DeviceID": device_id, "Data": data}]


def build_device_suffix(slave_id: str | int, idx: int, loop_prefix: str = "1") -> str:
    """
    Convert slave_id and idx (pin/channel) into a 3-digit HEX, then replace the highest digit with loop_prefix.
    - slave_id can be int or str; if str is not purely numeric, try base36 (supports alphanumeric IDs).
    - Calculation: code = slave * 0x10 + idx → format as %03X → replace the highest digit with loop_prefix.
    """

    def parse_sid(sid) -> int:
        if isinstance(sid, int):
            return sid
        s = str(sid).strip()
        # First try decimal (base10), then fallback to base36 (supports alphanumeric IDs)
        try:
            return int(s, 10)
        except Exception:
            return int(s, 36)

    sid = parse_sid(slave_id)
    code = sid * 0x10 + idx
    raw = f"{code:03X}"
    return f"{loop_prefix}{raw[1:]}"
