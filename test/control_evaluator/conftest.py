from unittest.mock import MagicMock

import pytest

from model.control_model import ControlActionModel, ControlActionType


@pytest.fixture
def mock_control_config():
    return MagicMock()


@pytest.fixture
def freq_action_30hz():
    return ControlActionModel(
        model="TECO_VFD",
        slave_id=2,
        type=ControlActionType.SET_FREQUENCY,
        target="RW_HZ",
        value=30.0,
    )


@pytest.fixture
def freq_action_50hz():
    return ControlActionModel(
        model="TECO_VFD",
        slave_id=2,
        type=ControlActionType.SET_FREQUENCY,
        target="RW_HZ",
        value=50.0,
    )


@pytest.fixture
def snapshot_all_high():
    return {
        "AIn01": 30.0,
        "AIn02": 20.0,
        "AIn03": 80.0,
        "AIn04": 40.0,
    }


@pytest.fixture
def snapshot_temp_trigger_only():
    return {
        "AIn01": 30.0,
        "AIn02": 20.0,
        "AIn03": 50.0,
        "AIn04": 40.0,
    }


@pytest.fixture
def snapshot_condition_not_met():
    return {
        "AIn01": 22.0,
        "AIn02": 20.0,
        "AIn03": 10.0,
        "AIn04": 5.0,
    }
