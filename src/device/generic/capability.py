def supports_on_off(device_type: str, register_map: dict) -> bool:
    cfg = register_map.get("RW_ON_OFF")
    if cfg and cfg.get("writable"):
        return True
    return device_type in {"inverter", "vfd", "inverter_vfd"}
