import pytest

from alert_config import AlertConfig


@pytest.fixture
def valid_device_ids():
    return {"TECO_VFD_1", "SD400_3", "SD400_7", "ADAM-4117_12"}


@pytest.fixture
def mock_alert_config() -> AlertConfig:
    """Alert config with threshold alerts using sources format"""
    return AlertConfig.model_validate(
        {
            "root": {
                "SD400": {
                    "default_alerts": [
                        {
                            "code": "AIN01_HIGH",
                            "name": "AIn01 overheat",
                            "sources": ["AIn01"],  # Changed from source to sources
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
                                    "sources": ["AIn02"],  # Changed from source to sources
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
                            "sources": ["ERROR"],  # Changed from source to sources
                            "condition": "gt",
                            "threshold": 0,
                            "severity": "ERROR",
                            "type": "threshold",
                        },
                        {
                            "code": "VFD_ALERT",
                            "name": "VFD Alert Code Active",
                            "sources": ["ALERT"],  # Changed from source to sources
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
    """Alert config with unknown device for testing skip logic"""
    return AlertConfig.model_validate(
        {
            "root": {
                "SD400": {
                    "default_alerts": [
                        {
                            "code": "AIN01_HIGH",
                            "name": "AIn01 overheat",
                            "sources": ["AIn01"],  # Changed from source to sources
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


@pytest.fixture
def mock_alert_config_with_aggregate() -> AlertConfig:
    """Alert config with aggregate types (average, sum, min, max)"""
    return AlertConfig.model_validate(
        {
            "root": {
                "ADAM-4117": {
                    "instances": {
                        "12": {
                            "alerts": [
                                # Average alert
                                {
                                    "code": "AVG_TEMP_HIGH",
                                    "name": "Average Temperature High",
                                    "sources": ["AIn02", "AIn03"],
                                    "condition": "gt",
                                    "threshold": 40.0,
                                    "severity": "CRITICAL",
                                    "type": "average",
                                },
                                # Sum alert
                                {
                                    "code": "TOTAL_TEMP_HIGH",
                                    "name": "Total Temperature High",
                                    "sources": ["AIn02", "AIn03"],
                                    "condition": "gt",
                                    "threshold": 80.0,
                                    "severity": "WARNING",
                                    "type": "sum",
                                },
                                # Min alert
                                {
                                    "code": "MIN_TEMP_LOW",
                                    "name": "Minimum Temperature Low",
                                    "sources": ["AIn02", "AIn03"],
                                    "condition": "lt",
                                    "threshold": 20.0,
                                    "severity": "WARNING",
                                    "type": "min",
                                },
                                # Max alert
                                {
                                    "code": "MAX_TEMP_HIGH",
                                    "name": "Maximum Temperature High",
                                    "sources": ["AIn02", "AIn03"],
                                    "condition": "gt",
                                    "threshold": 45.0,
                                    "severity": "CRITICAL",
                                    "type": "max",
                                },
                            ]
                        }
                    }
                }
            }
        }
    )
