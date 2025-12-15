from core.schema.constraint_schema import ConstraintConfigSchema
from core.util.config_manager import ConfigManager


def test_get_instance_pins_from_schema_should_return_pins_dict():
    raw = {
        "BAT08": {
            "instances": {
                "16": {
                    "pins": {
                        "AIn01": {"formula": [0, 0.01220703125, 0], "name": "Temp1"},
                        "AIn02": {"formula": [0, 0.01220703125, 0], "name": "Temp2"},
                    }
                }
            }
        }
    }

    schema = ConstraintConfigSchema(**raw)
    pins = ConfigManager.get_instance_pins_from_schema(schema, "BAT08", 16)

    assert pins["AIn01"]["formula"] == [0, 0.01220703125, 0]
    assert pins["AIn01"]["name"] == "Temp1"
    assert pins["AIn02"]["name"] == "Temp2"


def test_get_instance_pins_from_schema_should_return_empty_when_missing():
    raw = {"BAT08": {"instances": {"16": {}}}}
    schema = ConstraintConfigSchema(**raw)

    pins = ConfigManager.get_instance_pins_from_schema(schema, "BAT08", 16)
    assert pins == {}
