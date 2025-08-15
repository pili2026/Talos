from sender.legacy.snapshot_converters import (
    convert_ai_module_snapshot,
    convert_di_module_snapshot,
    convert_flow_meter,
    convert_inverter_snapshot,
)

CONVERTER_MAP = {
    "di_module": convert_di_module_snapshot,
    "ai_module": convert_ai_module_snapshot,
    "inverter": convert_inverter_snapshot,
    "flow_meter": convert_flow_meter,
}
