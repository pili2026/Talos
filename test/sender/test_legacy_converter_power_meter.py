import pytest

from core.sender.legacy.snapshot_converters import convert_power_meter_snapshot


class DummyPolicy:
    def build_device_id(self, gateway_id, slave_id, idx, eq_suffix):
        # 固定輸出，讓測試專心驗 Data
        return f"{gateway_id}_{slave_id}_{idx}{eq_suffix}"


@pytest.fixture(autouse=True)
def patch_policy(monkeypatch):
    monkeypatch.setattr("core.sender.legacy.snapshot_converters.get_policy", lambda: DummyPolicy())


def _data(result):
    assert isinstance(result, list) and len(result) == 1
    return result[0]["Data"]


def test_missing_common_fields_should_be_none():
    """
    Common fields missing => None (unsupported), NOT -1.
    Only Kwh provided.
    """
    values = {"Kwh": "12.34"}  # SW1100-like

    data = _data(convert_power_meter_snapshot("GW", 1, values))

    # common fields should be None if key not present
    assert data["AverageVoltage"] is None
    assert data["AverageCurrent"] is None
    assert data["Kw"] is None
    assert data["Kva"] is None
    assert data["Kvar"] is None
    assert data["AveragePowerFactor"] is None
    assert data["Phase_A_Current"] is None
    assert data["Phase_B_Current"] is None
    assert data["Phase_C_Current"] is None

    # Kwh is present
    assert data["Kwh"] == 12.34
    # Kvarh not present => None
    assert data["Kvarh"] is None


def test_present_but_failed_should_be_minus_one():
    """
    key present but value is '-1' => -1 (read failed), not None.
    """
    values = {"Kwh": "-1"}  # read failed

    data = _data(convert_power_meter_snapshot("GW", 1, values))
    assert data["Kwh"] == -1.0


def test_present_but_invalid_string_should_be_minus_one():
    """
    key present but invalid => -1 (read failed).
    """
    values = {"Kwh": "invalid"}

    data = _data(convert_power_meter_snapshot("GW", 1, values))
    assert data["Kwh"] == -1.0


def test_composed_sum_pattern_should_work():
    """
    Pattern 2: Kwh_SUM/Kvarh_SUM should be used when direct Kwh/Kvarh missing.
    """
    values = {
        "Kwh_SUM": "100.01",
        "Kvarh_SUM": "200.02",
    }

    data = _data(convert_power_meter_snapshot("GW", 1, values))
    assert data["Kwh"] == 100.01
    assert data["Kvarh"] == 200.02

    # unsupported common fields => None
    assert data["Kw"] is None
    assert data["AverageVoltage"] is None


def test_direct_pattern_should_override_sum_pattern():
    """
    If both Kwh and Kwh_SUM exist, prefer Kwh (pattern 1).
    """
    values = {
        "Kwh": "1.23",
        "Kwh_SUM": "999.99",
        "Kvarh": "4.56",
        "Kvarh_SUM": "888.88",
    }

    data = _data(convert_power_meter_snapshot("GW", 1, values))
    assert data["Kwh"] == 1.23
    assert data["Kvarh"] == 4.56


def test_legacy_3word_kwh_should_work_when_kwh_unsupported_and_raw_exists():
    """
    Pattern 3: When Kwh is None (unsupported) and Kwh_W1/2/3 exist, compute from 3 words.
    Use SCALE_EnergyIndex for scaling.
    """
    values = {
        "SCALE_EnergyIndex": "1",  # 1.0 * 0.001 = 0.001
        "Kwh_W1_HI": "0",
        "Kwh_W2_MD": "0",
        "Kwh_W3_LO": "1000",  # raw = 1000 -> 1000 * 0.001 = 1.0
    }

    data = _data(convert_power_meter_snapshot("GW", 1, values))
    assert data["Kwh"] == pytest.approx(1.0, rel=1e-9)


def test_legacy_3word_should_not_run_when_raw_missing():
    """
    If Kwh unsupported and raw 3-word registers missing => keep None.
    """
    values = {"SCALE_EnergyIndex": "1"}  # missing Kwh_W1/2/3

    data = _data(convert_power_meter_snapshot("GW", 1, values))
    assert data["Kwh"] is None


def test_rounding_applied_only_when_value_not_none():
    """
    Rounding should not crash on None fields.
    """
    values = {"Kwh": "1.23456"}  # should be rounded by POWER_METER_FIELDS["Kwh"]["round"] if defined

    data = _data(convert_power_meter_snapshot("GW", 1, values))
    # If POWER_METER_FIELDS defines Kwh round=2, expect 1.23
    # If it doesn't, this test should be adjusted to the configured precision.
    assert data["Kwh"] == pytest.approx(1.23, rel=1e-9)
