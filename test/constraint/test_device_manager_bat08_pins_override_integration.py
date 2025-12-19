import pytest

from core.schema.constraint_schema import ConstraintConfigSchema
from device_manager import AsyncDeviceManager


@pytest.mark.asyncio
async def test_device_manager_should_apply_bat08_pins_override(monkeypatch, tmp_path):
    """
    Integration-style test:
    - load modbus_device.yml (devices list)
    - load device_instance_config.yml (pins overrides)
    - init AsyncDeviceManager
    - assert register_map reflects per-instance pins overrides
    """

    # --- Patch Modbus connect to avoid touching real serial ports
    async def _fake_connect(self):
        return True

    monkeypatch.setattr("device_manager.AsyncModbusSerialClient.connect", _fake_connect)

    # --- Prepare model driver: minimal BAT08 driver (generic pins, will be overridden by instance pins)
    model_dir = tmp_path / "res"
    model_dir.mkdir(parents=True, exist_ok=True)

    bat08_driver = {
        "model": "BAT08",
        "register_type": "holding",
        "type": "ai_module",
        "register_map": {
            # baseline generic pins; instance pins should override these fields
            "AIn01": {
                "offset": 0,
                "format": "i16",
                "formula": [0, 1, 0],
                "type": "analog",
                "unit": "",
                "precision": 3,
                "readable": True,
                "writable": False,
            },
            "AIn02": {
                "offset": 1,
                "format": "i16",
                "formula": [0, 1, 0],
                "type": "analog",
                "unit": "",
                "precision": 3,
                "readable": True,
                "writable": False,
            },
            "AIn03": {
                "offset": 2,
                "format": "i16",
                "formula": [0, 1, 0],
                "type": "analog",
                "unit": "",
                "precision": 3,
                "readable": True,
                "writable": False,
            },
            "AIn04": {
                "offset": 3,
                "format": "i16",
                "formula": [0, 1, 0],
                "type": "analog",
                "unit": "",
                "precision": 3,
                "readable": True,
                "writable": False,
            },
            "AIn05": {
                "offset": 4,
                "format": "i16",
                "formula": [0, 1, 0],
                "type": "analog",
                "unit": "",
                "precision": 3,
                "readable": True,
                "writable": False,
            },
            "AIn06": {
                "offset": 5,
                "format": "i16",
                "formula": [0, 1, 0],
                "type": "analog",
                "unit": "",
                "precision": 3,
                "readable": True,
                "writable": False,
            },
            "AIn07": {
                "offset": 6,
                "format": "i16",
                "formula": [0, 1, 0],
                "type": "analog",
                "unit": "",
                "precision": 3,
                "readable": True,
                "writable": False,
            },
            "AIn08": {
                "offset": 7,
                "format": "i16",
                "formula": [0, 1, 0],
                "type": "analog",
                "unit": "",
                "precision": 3,
                "readable": True,
                "writable": False,
            },
        },
    }

    (model_dir / "bat08.yml").write_text(
        __import__("yaml").safe_dump(bat08_driver, sort_keys=False),
        encoding="utf-8",
    )

    # --- Prepare modbus_device.yml
    modbus_device = {
        "devices": [
            {
                "id": "bat08_16",
                "model": "BAT08",
                "model_file": "bat08.yml",
                "port": "/tmp/ttyFAKE0",
                "slave_id": "16",
                "type": "ai_module",
            },
            {
                "id": "bat08_17",
                "model": "BAT08",
                "model_file": "bat08.yml",
                "port": "/tmp/ttyFAKE0",
                "slave_id": "17",
                "type": "ai_module",
            },
            {
                "id": "bat08_19",
                "model": "BAT08",
                "model_file": "bat08.yml",
                "port": "/tmp/ttyFAKE0",
                "slave_id": "19",
                "type": "ai_module",
            },
            {
                "id": "bat08_20",
                "model": "BAT08",
                "model_file": "bat08.yml",
                "port": "/tmp/ttyFAKE0",
                "slave_id": "20",
                "type": "ai_module",
            },
        ]
    }
    modbus_device_path = tmp_path / "modbus_device.yml"
    modbus_device_path.write_text(__import__("yaml").safe_dump(modbus_device, sort_keys=False), encoding="utf-8")

    # --- Prepare instance config (pins overrides)
    instance_raw = {
        "BAT08": {
            "default_constraints": {},
            # model-level baseline (room1)
            "pins": {
                "AIn01": {
                    "name": "Temp1",
                    "formula": [0, 0.01220703125, 0.0],
                    "type": "thermometer",
                    "unit": "°C",
                    "precision": 2,
                },
                "AIn02": {
                    "name": "Temp2",
                    "formula": [0, 0.01220703125, 0.0],
                    "type": "thermometer",
                    "unit": "°C",
                    "precision": 2,
                },
                "AIn03": {
                    "name": "Pressure3",
                    "formula": [0, 0.00097656, 0.0],
                    "type": "pressure",
                    "unit": "bar",
                    "precision": 3,
                },
                "AIn04": {
                    "name": "Temp4",
                    "formula": [0, 0.01220703125, 0.0],
                    "type": "thermometer",
                    "unit": "°C",
                    "precision": 2,
                },
                "AIn05": {
                    "name": "Temp5",
                    "formula": [0, 0.01220703125, 0.0],
                    "type": "thermometer",
                    "unit": "°C",
                    "precision": 2,
                },
                "AIn06": {
                    "name": "Pressure6",
                    "formula": [0, 0.00097656, 0.0],
                    "type": "pressure",
                    "unit": "bar",
                    "precision": 3,
                },
                "AIn07": {
                    "name": "Temp7",
                    "formula": [0, 0.01220703125, 0.0],
                    "type": "thermometer",
                    "unit": "°C",
                    "precision": 2,
                },
                "AIn08": {
                    "name": "Temp8",
                    "formula": [0, 0.01220703125, 0.0],
                    "type": "thermometer",
                    "unit": "°C",
                    "precision": 2,
                },
            },
            "instances": {
                "16": {},
                "17": {
                    "pins": {
                        "AIn01": {"formula": [0, 0.01220703125, -1.5]},
                        "AIn02": {"formula": [0, 0.01220703125, -1.4]},
                        "AIn04": {"formula": [0, 0.01220703125, 3.0]},
                        "AIn05": {"formula": [0, 0.01220703125, 1.0]},
                    }
                },
                "19": {
                    "pins": {
                        "AIn01": {"formula": [0, 0.01220703125, -1.0]},
                        "AIn02": {"formula": [0, 0.01220703125, -1.0]},
                    }
                },
                "20": {
                    "pins": {
                        "AIn01": {"formula": [0, 0.01220703125, -1.4]},
                        "AIn02": {"formula": [0, 0.01220703125, -1.0]},
                        "AIn04": {"formula": [0, 0.01220703125, -1.0]},
                        "AIn05": {"formula": [0, 0.01220703125, -1.0]},
                    }
                },
            },
        }
    }

    schema = ConstraintConfigSchema(**instance_raw)

    # --- Init DeviceManager
    mgr = AsyncDeviceManager(
        config_path=str(modbus_device_path),
        constraint_config_schema=schema,
        model_base_path=str(model_dir),
    )
    await mgr.init()

    d16 = mgr.get_device_by_model_and_slave_id("BAT08", 16)
    d17 = mgr.get_device_by_model_and_slave_id("BAT08", 17)
    d19 = mgr.get_device_by_model_and_slave_id("BAT08", 19)
    d20 = mgr.get_device_by_model_and_slave_id("BAT08", 20)

    assert d16 and d17 and d19 and d20

    # --- Baseline instance should carry full pin metadata
    assert d16.register_map["AIn03"]["type"] == "pressure"
    assert d16.register_map["AIn03"]["unit"] == "bar"
    assert d16.register_map["AIn03"]["precision"] == 3
    assert d16.register_map["AIn01"]["formula"] == [0, 0.01220703125, 0.0]

    # --- room5 overrides (17): only formula N3 differs for some temp pins, others inherited from 16
    assert d17.register_map["AIn01"]["formula"] == [0, 0.01220703125, -1.5]
    assert d17.register_map["AIn02"]["formula"] == [0, 0.01220703125, -1.4]
    assert d17.register_map["AIn03"]["formula"] == [0, 0.00097656, 0.0]  # unchanged
    assert d17.register_map["AIn03"]["type"] == "pressure"  # inherited baseline
    assert d17.register_map["AIn03"]["unit"] == "bar"

    # --- room6 overrides (19)
    assert d19.register_map["AIn01"]["formula"] == [0, 0.01220703125, -1.0]
    assert d19.register_map["AIn02"]["formula"] == [0, 0.01220703125, -1.0]
    assert d19.register_map["AIn06"]["type"] == "pressure"

    # --- room7 overrides (20)
    assert d20.register_map["AIn01"]["formula"] == [0, 0.01220703125, -1.4]
    assert d20.register_map["AIn04"]["formula"] == [0, 0.01220703125, -1.0]
    assert d20.register_map["AIn05"]["formula"] == [0, 0.01220703125, -1.0]
    assert d20.register_map["AIn08"]["name"] == "Temp8"  # inherited baseline
