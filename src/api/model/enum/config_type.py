from enum import StrEnum


class ConfigTypeEnum(StrEnum):
    SYSTEM_CONFIG = "system_config"
    MODBUS_DEVICE = "modbus_device"
    DEVICE_INSTANCE = "device_instance_config"
    ALERT_CONFIG = "alert_config"
    CONTROL_CONFIG = "control_config"
    PIN_MAPPING = "pin_mapping"
