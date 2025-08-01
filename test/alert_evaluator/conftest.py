import pytest

from alert_config import AlertConfig


@pytest.fixture
def valid_device_ids():
    return {"TECO_VFD_1", "SD400_3", "SD400_7"}


@pytest.fixture
def mock_alert_config() -> AlertConfig:
    return AlertConfig.model_validate(
        {
            "root": {
                "SD400": {
                    "default_alerts": [
                        {
                            "code": "AIN01_HIGH",
                            "name": "AIn01 overheat",
                            "source": "AIn01",
                            "condition": "gt",
                            "threshold": 49.0,
                            "severity": "WARNING",
                            "type": "threshold",
                        }
                    ],
                    "instances": {
                        "3": {"use_default_alerts": True},
                        "7": {
                            "alerts": [
                                {
                                    "code": "AIN02_LOW",
                                    "name": "AIn02 low temp",
                                    "source": "AIn02",
                                    "condition": "lt",
                                    "threshold": 5.0,
                                    "severity": "WARNING",
                                    "type": "threshold",
                                }
                            ]
                        },
                        "9": {"use_default_alerts": False},
                    },
                },
                "TECO_VFD": {
                    "default_alerts": [
                        {
                            "code": "VFD_ERROR",
                            "name": "VFD Error Code Active",
                            "source": "ERROR",
                            "condition": "gt",
                            "threshold": 0,
                            "severity": "ERROR",
                            "type": "threshold",
                        },
                        {
                            "code": "VFD_ALERT",
                            "name": "VFD Alert Code Active",
                            "source": "ALERT",
                            "condition": "gt",
                            "threshold": 0,
                            "severity": "WARNING",
                            "type": "threshold",
                        },
                    ],
                    "instances": {"1": {"use_default_alerts": True, "display_name": "Main VFD"}},
                },
            }
        }
    )


@pytest.fixture
def mock_alert_config_with_unknown_device() -> AlertConfig:
    return AlertConfig.model_validate(
        {
            "root": {
                "SD400": {
                    "default_alerts": [
                        {
                            "code": "AIN01_HIGH",
                            "name": "AIn01 overheat",
                            "source": "AIn01",
                            "condition": "gt",
                            "threshold": 49.0,
                            "severity": "WARNING",
                            "type": "threshold",
                        }
                    ],
                    "instances": {"999": {"use_default_alerts": True}},  # Unknown device ID
                }
            }
        }
    )
