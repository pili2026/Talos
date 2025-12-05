# FIXME Need to Refactor

from core.sender.legacy.snapshot_converters import (
    convert_ai_module_snapshot,
    convert_di_module_snapshot,
    convert_inverter_snapshot,
    convert_panel_meter_snapshot,
    convert_power_meter_snapshot,
    convert_sensor_snapshot,
)

CONVERTER_MAP = {
    "di_module": convert_di_module_snapshot,
    "ai_module": convert_ai_module_snapshot,
    "inverter": convert_inverter_snapshot,
    "power_meter": convert_power_meter_snapshot,
    "sensor": convert_sensor_snapshot,
    "panel_meter": convert_panel_meter_snapshot,
}
