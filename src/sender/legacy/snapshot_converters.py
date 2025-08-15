import logging

logger = logging.getLogger("SnapshotConverter")


def convert_di_module_snapshot(gateway_id: str, slave_id: str, snapshot: dict[str, str]) -> list[dict]:
    result = []

    for i in range(1, 17):
        key = f"DIn{i:02d}"
        if key not in snapshot:
            continue
        try:
            relay = int(float(snapshot[key]))
        except Exception:
            continue

        suffix = build_device_suffix(slave_id, i - 1) + "SR"
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

    suffix = build_device_suffix(slave_id, 0) + "CI"
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
        "Temp": "st",
        "Pressure": "sp",
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
    suffix = build_device_suffix(slave_id, 0) + "SF"
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


def build_device_suffix(slave_id: str, idx: int, loop_prefix: str = "1") -> str:
    raw = f"{(slave_id * 0x10 + idx):03X}"
    fixed = loop_prefix + raw[1:]
    return fixed
