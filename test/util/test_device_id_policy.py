import pytest

from core.model.enum.equipment_enum import EquipmentType
from core.schema.system_config_schema import DeviceIdPolicyConfig
from core.util.device_id_policy import DeviceIdPolicy


class TestDeviceIdPolicyDevice36:
    """Tests for DeviceIdPolicy in DEVICE36 mode."""

    def _make_policy(
        self,
        series: int = 0,
        width: int = 3,
        radix: str = "device36",
        uppercase: bool = True,
        prefix: str = "",
    ) -> DeviceIdPolicy:
        cfg = DeviceIdPolicyConfig(
            SERIES=series,
            WIDTH=width,
            RADIX=radix,
            UPPERCASE=uppercase,
            PREFIX=prefix,
        )
        return DeviceIdPolicy(cfg)

    def test_slave_1_idx_0_should_be_010(self):
        policy = self._make_policy(series=0, uppercase=True)
        code = policy.generate_code(slave_id=1, idx=0)
        assert code == "010"

    def test_slave_10_idx_0_should_be_0A0(self):
        policy = self._make_policy(series=0, uppercase=True)
        code = policy.generate_code(slave_id=10, idx=0)
        assert code == "0A0"

    def test_slave_15_idx_0_should_be_0F0(self):
        policy = self._make_policy(series=0, uppercase=True)
        code = policy.generate_code(slave_id=15, idx=0)
        assert code == "0F0"

    def test_slave_16_idx_0_should_be_0G0(self):
        """Key case: slave=16 → 'G' in base-36."""
        policy = self._make_policy(series=0, uppercase=True)
        code = policy.generate_code(slave_id=16, idx=0)
        assert code == "0G0"

    def test_slave_35_idx_0_should_be_0Z0(self):
        """Upper bound: slave=35 → 'Z'."""
        policy = self._make_policy(series=0, uppercase=True)
        code = policy.generate_code(slave_id=35, idx=0)
        assert code == "0Z0"

    def test_slave_over_35_should_be_clamped_to_Z(self):
        """Out-of-range slave_id should be clamped to 35 (Z)."""
        policy = self._make_policy(series=0, uppercase=True)
        code = policy.generate_code(slave_id=100, idx=0)
        assert code == "0Z0"

    def test_idx_over_15_should_be_clamped_to_0(self):
        """Out-of-range idx should fallback to 0."""
        policy = self._make_policy(series=0, uppercase=True)
        code = policy.generate_code(slave_id=16, idx=99)
        # slave=16 → G, idx fallback to 0 → "0G0"
        assert code == "0G0"

    def test_lowercase_mode_should_use_lowercase_letters(self):
        policy = self._make_policy(series=0, uppercase=False)
        code = policy.generate_code(slave_id=16, idx=0)
        assert code == "0g0"

    def test_build_device_id_should_match_legacy_format(self):
        policy = self._make_policy(series=0, uppercase=True)
        device_id = policy.build_device_id(
            gateway_id="05346051113",
            slave_id=16,
            idx=0,
            eq_suffix=EquipmentType.SE,  # SE suffix (e.g. power meter)
        )
        assert device_id == "05346051113_0G0SE"

    @pytest.mark.parametrize(
        "series,expected",
        [
            (0, "010"),  # series=0 → '0'
            (1, "110"),  # series=1 → '1'
            (10, "A10"),  # series=10 → 'A'
            (15, "F10"),  # series=15 → 'F'
        ],
    )
    def test_series_encoding_in_device36(self, series: int, expected: str):
        """Series is encoded in the first character (0..F)."""
        policy = self._make_policy(series=series, uppercase=True)
        code = policy.generate_code(slave_id=1, idx=0)
        assert code == expected
