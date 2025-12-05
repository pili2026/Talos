from core.sender.legacy.snapshot_converters import _get_do_state_for_di, convert_di_module_snapshot


def test_di_module_with_invalid_pin_value():
    """Test that invalid DI pin values generate -1 records instead of being skipped"""
    snapshot = {"DIn01": "1", "DIn02": "invalid_value", "DIn03": "0"}

    result = convert_di_module_snapshot("GW123", "5", snapshot, "IMA_C")

    assert len(result) == 3
    assert result[1]["Data"]["Relay0"] == -1


def test_get_do_state_for_di_with_missing_value():
    """Test that -1 DOut values are preserved"""
    snapshot = {"DOut01": "-1"}

    result = _get_do_state_for_di(snapshot, 1, "IMA_C")

    assert result == -1
