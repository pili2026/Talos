from sender.legacy.snapshot_converters import (  # convert_flow_meter,
    convert_ai_module_snapshot,
    convert_di_module_snapshot,
    convert_inverter_snapshot,
    convert_power_meter_snapshot,
)

CONVERTER_MAP = {
    "di_module": convert_di_module_snapshot,
    "ai_module": convert_ai_module_snapshot,
    "inverter": convert_inverter_snapshot,
    # "flow_meter": convert_flow_meter, # TODO: Cloud API does not support flow meter yet
    "power_meter": convert_power_meter_snapshot,
}
