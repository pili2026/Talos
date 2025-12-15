import copy
import logging

from device_manager import _merge_register_map_with_pins


def test_merge_register_map_with_pins_should_override_without_mutating_base(caplog):
    caplog.set_level(logging.INFO)

    base_register_map = {
        "AIn01": {"offset": 0, "format": "i16", "formula": [0, 1, 0], "readable": True},
        "AIn02": {"offset": 1, "format": "i16", "formula": [0, 1, 0], "readable": True},
    }
    base_snapshot = copy.deepcopy(base_register_map)

    pins_override = {
        "AIn01": {"formula": [0, 0.01220703125, -1.5]},
    }

    out = _merge_register_map_with_pins(
        driver_register_map=base_register_map,
        pins_override=pins_override,
        logger=logging.getLogger("test"),
        device_id="BAT08_17",
    )

    assert out["AIn01"]["formula"] == [0, 0.01220703125, -1.5]
    assert out["AIn02"]["formula"] == [0, 1, 0]
    assert base_register_map == base_snapshot


def test_merge_register_map_with_pins_should_warn_and_skip_unknown_pin(caplog):
    caplog.set_level(logging.WARNING)

    base_register_map = {
        "AIn01": {"offset": 0, "format": "i16", "formula": [0, 1, 0], "readable": True},
    }

    pins_override = {
        "AIn99": {"formula": [0, 2, 0]},
    }

    out = _merge_register_map_with_pins(
        driver_register_map=base_register_map,
        pins_override=pins_override,
        logger=logging.getLogger("test"),
        device_id="BAT08_16",
    )

    assert "AIn01" in out
    assert "AIn99" not in out
    assert "unknown pin" in caplog.text.lower()
