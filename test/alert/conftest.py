from datetime import time
from unittest.mock import Mock

import pytest

from core.evaluator.time_evalutor import TimeControlEvaluator
from core.schema.alert_config_schema import AlertConfig
from core.schema.time_control_schema import DeviceSchedule, TimeControlConfig, TimeInterval


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
                            "device_name": "SD400 Temperature Sensor",
                            "sources": ["AIn01"],
                            "condition": "gt",
                            "threshold": 49.0,
                            "severity": "WARNING",
                            "type": "threshold",
                            "message": "Temperature reading from AIn01 is too high",
                        }
                    ],
                    "instances": {
                        "3": {"use_default_alerts": True},
                        "7": {
                            "alerts": [
                                {
                                    "code": "AIN02_LOW",
                                    "name": "AIn02 low temp",
                                    "device_name": "SD400 Temperature Sensor",
                                    "sources": ["AIn02"],
                                    "condition": "lt",
                                    "threshold": 5.0,
                                    "severity": "WARNING",
                                    "type": "threshold",
                                    "message": "Temperature reading from AIn02 is too low",
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
                            "device_name": "Main VFD",
                            "sources": ["ERROR"],
                            "condition": "gt",
                            "threshold": 0,
                            "severity": "ERROR",
                            "type": "threshold",
                            "message": "VFD error code is active",
                        },
                        {
                            "code": "VFD_ALERT",
                            "name": "VFD Alert Code Active",
                            "device_name": "Main VFD",
                            "sources": ["ALERT"],
                            "condition": "gt",
                            "threshold": 0,
                            "severity": "WARNING",
                            "type": "threshold",
                            "message": "VFD alert code is active",
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
                            "device_name": "SD400 Temperature Sensor",
                            "sources": ["AIn01"],
                            "condition": "gt",
                            "threshold": 49.0,
                            "severity": "WARNING",
                            "type": "threshold",
                            "message": "Temperature reading is too high",
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
                                    "device_name": "ADAM-4117 Multi-Point Sensor",
                                    "sources": ["AIn02", "AIn03"],
                                    "condition": "gt",
                                    "threshold": 40.0,
                                    "severity": "CRITICAL",
                                    "type": "average",
                                    "message": "Average temperature across sensors exceeds threshold",
                                },
                                # Sum alert
                                {
                                    "code": "TOTAL_TEMP_HIGH",
                                    "name": "Total Temperature High",
                                    "device_name": "ADAM-4117 Multi-Point Sensor",
                                    "sources": ["AIn02", "AIn03"],
                                    "condition": "gt",
                                    "threshold": 80.0,
                                    "severity": "WARNING",
                                    "type": "sum",
                                    "message": "Total temperature reading exceeds threshold",
                                },
                                # Min alert
                                {
                                    "code": "MIN_TEMP_LOW",
                                    "name": "Minimum Temperature Low",
                                    "device_name": "ADAM-4117 Multi-Point Sensor",
                                    "sources": ["AIn02", "AIn03"],
                                    "condition": "lt",
                                    "threshold": 20.0,
                                    "severity": "WARNING",
                                    "type": "min",
                                    "message": "Minimum temperature reading is too low",
                                },
                                # Max alert
                                {
                                    "code": "MAX_TEMP_HIGH",
                                    "name": "Maximum Temperature High",
                                    "device_name": "ADAM-4117 Multi-Point Sensor",
                                    "sources": ["AIn02", "AIn03"],
                                    "condition": "gt",
                                    "threshold": 45.0,
                                    "severity": "CRITICAL",
                                    "type": "max",
                                    "message": "Maximum temperature reading exceeds threshold",
                                },
                            ]
                        }
                    }
                }
            }
        }
    )


# ============================================================
# New Fixtures for Schedule Expected State Alerts
# ============================================================


@pytest.fixture
def mock_alert_config_with_schedule() -> AlertConfig:
    """Alert config with schedule_expected_state alert"""
    return AlertConfig.model_validate(
        {
            "root": {
                "TECO_VFD": {
                    "instances": {
                        "1": {
                            "alerts": [
                                {
                                    "code": "BLOWER_AFTER_HOURS",
                                    "name": "Blower Running After Hours",
                                    "device_name": "Main Blower VFD",
                                    "sources": ["RW_ON_OFF"],
                                    "type": "schedule_expected_state",
                                    "expected_state": 0,
                                    "severity": "WARNING",
                                    "message": "Blower is running outside of scheduled hours",
                                }
                            ]
                        }
                    }
                }
            }
        }
    )


@pytest.fixture
def mock_alert_config_with_schedule_expected_on() -> AlertConfig:
    """Alert config with schedule_expected_state expecting ON state"""
    return AlertConfig.model_validate(
        {
            "root": {
                "COOLING": {
                    "instances": {
                        "1": {
                            "alerts": [
                                {
                                    "code": "COOLING_MUST_RUN",
                                    "name": "Cooling System Must Run 24/7",
                                    "device_name": "Critical Cooling System",
                                    "sources": ["RW_ON_OFF"],
                                    "type": "schedule_expected_state",
                                    "expected_state": 1,  # Expect ON
                                    "severity": "CRITICAL",
                                    "message": "Cooling system must remain on at all times",
                                }
                            ]
                        }
                    }
                }
            }
        }
    )


@pytest.fixture
def mock_alert_config_with_schedule_threshold() -> AlertConfig:
    """Alert config with schedule_threshold alert (night power monitoring)"""
    return AlertConfig.model_validate(
        {
            "root": {
                "ADTEK_CPM10": {
                    "instances": {
                        "1": {
                            "alerts": [
                                {
                                    "code": "NIGHT_KW_HIGH",
                                    "name": "用電異常（夜間）",
                                    "device_name": "Power Meter",
                                    "sources": ["Kw"],
                                    "type": "schedule_threshold",
                                    "condition": "gt",
                                    "threshold": 10.0,
                                    "active_hours": {
                                        "start": "20:00",
                                        "end": "07:00",
                                    },
                                    "severity": "WARNING",
                                }
                            ]
                        }
                    }
                }
            }
        }
    )


@pytest.fixture
def mock_alert_config_with_schedule_threshold_daytime() -> AlertConfig:
    """Alert config with schedule_threshold alert (daytime, non-overnight)"""
    return AlertConfig.model_validate(
        {
            "root": {
                "ADTEK_CPM10": {
                    "instances": {
                        "1": {
                            "alerts": [
                                {
                                    "code": "DAY_KW_HIGH",
                                    "name": "用電異常（日間）",
                                    "device_name": "Power Meter",
                                    "sources": ["Kw"],
                                    "type": "schedule_threshold",
                                    "condition": "gt",
                                    "threshold": 10.0,
                                    "active_hours": {
                                        "start": "08:00",
                                        "end": "18:00",
                                    },
                                    "severity": "WARNING",
                                }
                            ]
                        }
                    }
                }
            }
        }
    )


@pytest.fixture
def mock_time_evaluator():
    """Create mock TimeControlEvaluator"""
    return Mock(spec=TimeControlEvaluator)


@pytest.fixture
def time_control_config_weekday_9_to_18():
    """Time control config with work hours 09:00-18:00 weekdays"""
    return TimeControlConfig(
        timezone="Asia/Taipei",
        work_hours={
            "TECO_VFD_1": DeviceSchedule(
                weekdays={1, 2, 3, 4, 5}, intervals=[TimeInterval(start=time(9, 0), end=time(18, 0))]  # Mon-Fri
            )
        },
    )


@pytest.fixture
def real_time_evaluator(time_control_config_weekday_9_to_18):
    """Create real TimeControlEvaluator for integration tests"""
    return TimeControlEvaluator(time_control_config_weekday_9_to_18)
