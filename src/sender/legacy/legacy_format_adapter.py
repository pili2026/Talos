import logging
from datetime import datetime

from sender.legacy.legacy_util import extract_model_and_slave_id

logger = logging.getLogger("LegacyFormatAdapter")


def convert_ima_c_snapshot(gateway_id: str, model: str, slave_id: int, snapshot: dict[str, str]) -> list[dict]:
    base_id = slave_id * 10
    result = []

    for i in range(1, 17):
        key = f"DIn{i:02d}"
        if key not in snapshot:
            continue

        try:
            relay = int(float(snapshot[key]))
        except Exception:
            continue

        device_suffix = f"{base_id + i - 1:03d}SR"
        device_id = f"{gateway_id}_{device_suffix}"

        data = {
            "Relay0": relay,
            "Relay1": 0,
            "MCStatus0": int(float(snapshot.get("DOut01", "0"))),
            "MCStatus1": int(float(snapshot.get("DOut02", "0"))),
            "ByPass": int(float(snapshot.get("ByPass", "0"))),
        }

        result.append({"DeviceID": device_id, "Data": data})

    return result


def convert_teco_vfd_snapshot(gateway_id: str, model: str, slave_id: int, snapshot: dict[str, str]) -> list[dict]:
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

    device_suffix = f"{slave_id * 10:03d}CI"
    device_id = f"{gateway_id}_{device_suffix}"

    data = {}
    for raw_key, (target_key, caster) in field_map.items():
        val = snapshot.get(raw_key)
        if val is not None:
            try:
                data[target_key] = caster(float(val))
            except Exception:
                continue

    return [{"DeviceID": device_id, "Data": data}] if data else []


def convert_sd400_snapshot(gateway_id: str, model: str, slave_id: int, snapshot: dict[str, str]) -> list[dict]:
    sensor_type_map = {
        "AIn01": "Temp",
        "AIn02": "Temp",
        "AIn03": "Pressure",
        "AIn04": "Temp",
        "AIn05": "Temp",
        "AIn06": "Pressure",
        "AIn07": "Temp",
        "AIn08": "Temp",
    }

    base_id = slave_id * 10
    result = []

    for idx, (ain_key, sensor_type) in enumerate(sensor_type_map.items()):
        val = snapshot.get(ain_key)
        if val is None:
            continue
        try:
            value = float(val)
        except ValueError:
            continue

        suffix = f"{base_id + idx:03d}" + ("ST" if sensor_type == "Temp" else "SP")
        device_id = f"{gateway_id}_{suffix}"

        result.append({"DeviceID": device_id, "Data": {sensor_type: value}})

    return result


# TODO: SUB snapsht and get type to process
def convert_snapshot_to_legacy_payload(gateway_id: str, snapshot_map: dict[str, dict[str, str]]) -> dict:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    data_list = []

    for device_key, snapshot in snapshot_map.items():
        try:
            model, slave_id_str = extract_model_and_slave_id(device_key)
            slave_id = int(slave_id_str)

            if model == "IMA_C":
                data_list.extend(convert_ima_c_snapshot(gateway_id, model, slave_id, snapshot))
            elif model == "TECO_VFD":
                data_list.extend(convert_teco_vfd_snapshot(gateway_id, model, slave_id, snapshot))
            elif model == "SD400":
                data_list.extend(convert_sd400_snapshot(gateway_id, model, slave_id, snapshot))
            else:
                logger.debug(f"[LegacyFormat] Skip model {model} (not supported)")

        except Exception as e:
            logger.warning(f"[LegacyFormat] Error converting {device_key}: {e}")

    return {
        "FUNC": "PushIMAData",
        "version": "6.0",
        "GatewayID": gateway_id,
        "Timestamp": timestamp,
        "Data": data_list,
    }
