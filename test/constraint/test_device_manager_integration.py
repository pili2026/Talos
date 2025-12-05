import logging
from unittest.mock import AsyncMock, Mock, patch

import pytest

from core.device.generic.constraints_policy import ConstraintPolicy
from core.device.generic.generic_device import AsyncGenericModbusDevice
from core.schema.constraint_schema import ConstraintConfig, ConstraintConfigSchema
from device_manager import AsyncDeviceManager


@pytest.mark.asyncio
class TestAsyncDeviceManagerStartupFrequency:
    @pytest.fixture
    def sample_constraint_config(self):
        """Provide a sample constraint configuration for tests"""
        # Arrange
        return ConstraintConfigSchema(
            **{
                "global_defaults": {"initialization": {"startup_frequency": 50.0}},
                "LITEON_EVO6800": {
                    "initialization": {"startup_frequency": 45.0},
                    "default_constraints": {"RW_HZ": {"min": 30, "max": 55}},
                    "instances": {
                        "1": {
                            "initialization": {"startup_frequency": 52.0},
                            "constraints": {"RW_HZ": {"min": 55, "max": 57}},
                        },
                        "2": {
                            "initialization": {"startup_frequency": 25.0},  # below constraint min
                            "constraints": {"RW_HZ": {"min": 40, "max": 60}},
                        },
                        "3": {
                            "initialization": {"startup_frequency": 70.0},  # above constraint max
                            "constraints": {"RW_HZ": {"min": 40, "max": 60}},
                        },
                        "4": {
                            # no startup_frequency, and min == max
                            "constraints": {"RW_HZ": {"min": 60, "max": 60}}
                        },
                    },
                },
                "TECO_VFD": {
                    "default_constraints": {"RW_HZ": {"min": 55, "max": 59}}
                    # no initialization → should use global_defaults
                },
            }
        )

    @pytest.fixture
    def mock_device(self):
        """Create a mock device"""
        # Arrange
        device = Mock(spec=AsyncGenericModbusDevice)
        device.model = "LITEON_EVO6800"
        device.slave_id = 1
        device.write_value = AsyncMock()

        # Mock ConstraintPolicy
        mock_constraint_policy = Mock(spec=ConstraintPolicy)
        mock_constraint_policy.allow = Mock(return_value=True)
        mock_constraint_policy.constraints = {"RW_HZ": ConstraintConfig(min=55.0, max=57.0)}
        device.constraints = mock_constraint_policy

        # Act & Assert handled in individual tests
        return device

    @pytest.fixture
    def device_manager(self, sample_constraint_config):
        """Create an AsyncDeviceManager instance with mocked ConfigManager"""
        # Arrange
        with patch("device_manager.ConfigManager") as mock_config_manager:
            mock_config_manager.return_value.load_yaml_file.return_value = {"devices": []}  # avoid real init
            manager = AsyncDeviceManager(config_path="dummy_path", constraint_config_schema=sample_constraint_config)
            # Act & Assert handled in individual tests
            return manager

    async def test_when_startup_frequency_within_constraints_then_sets_requested_value(
        self, device_manager, mock_device
    ):
        """Test that when startup frequency is within constraints, the requested value is written"""
        # Arrange
        device_manager.device_list = [mock_device]

        # Act
        with patch("device_manager.ConfigManager.get_device_startup_frequency", return_value=56):
            await device_manager._apply_startup_frequency()

        # Assert
        mock_device.constraints.allow.assert_called_once_with("RW_HZ", 56.0)
        mock_device.write_value.assert_called_once_with("RW_HZ", 56.0)

    async def test_when_startup_frequency_below_minimum_then_sets_minimum_value(self, device_manager):
        """Test that when startup frequency is below the minimum, the minimum value is used"""
        # Arrange
        mock_device = Mock(spec=AsyncGenericModbusDevice)
        mock_device.model = "LITEON_EVO6800"
        mock_device.slave_id = 2
        mock_device.write_value = AsyncMock()

        # Reject original value but allow corrected min value
        mock_constraint_policy = Mock(spec=ConstraintPolicy)
        mock_constraint_policy.allow = Mock(side_effect=lambda target, value: value >= 40.0)
        mock_constraint_policy.constraints = {"RW_HZ": ConstraintConfig(min=40.0, max=60.0)}
        mock_device.constraints = mock_constraint_policy

        device_manager.device_list = [mock_device]

        # Act
        with patch("device_manager.ConfigManager.get_device_startup_frequency", return_value=25):
            await device_manager._apply_startup_frequency()

        # Assert
        mock_device.write_value.assert_called_once_with("RW_HZ", 40.0)

    async def test_when_startup_frequency_above_maximum_then_sets_minimum_value(self, device_manager):
        """Test that when startup frequency is above the maximum, the safe minimum value is used"""
        # Arrange
        mock_device = Mock(spec=AsyncGenericModbusDevice)
        mock_device.model = "LITEON_EVO6800"
        mock_device.slave_id = 3
        mock_device.write_value = AsyncMock()

        # Reject original value but allow corrected range; policy leads to choosing min as safe value
        mock_constraint_policy = Mock(spec=ConstraintPolicy)
        mock_constraint_policy.allow = Mock(side_effect=lambda target, value: 40.0 <= value <= 60.0)
        mock_constraint_policy.constraints = {"RW_HZ": ConstraintConfig(min=40.0, max=60.0)}
        mock_device.constraints = mock_constraint_policy

        device_manager.device_list = [mock_device]

        # Act
        with patch("device_manager.ConfigManager.get_device_startup_frequency", return_value=70):
            await device_manager._apply_startup_frequency()

        # Assert
        # Should use the lower bound (safe minimum) rather than the upper bound
        mock_device.write_value.assert_called_once_with("RW_HZ", 40.0)

    async def test_when_constraints_have_same_min_max_and_conflict_then_sets_constraint_value(self, device_manager):
        """Test that when min==max and requested value conflicts, the constraint value is used"""
        # Arrange
        mock_device = Mock(spec=AsyncGenericModbusDevice)
        mock_device.model = "LITEON_EVO6800"
        mock_device.slave_id = 4
        mock_device.write_value = AsyncMock()

        # Only 60 Hz is allowed
        mock_constraint_policy = Mock(spec=ConstraintPolicy)
        mock_constraint_policy.allow = Mock(side_effect=lambda target, value: value == 60.0)
        mock_constraint_policy.constraints = {"RW_HZ": ConstraintConfig(min=60.0, max=60.0)}
        mock_device.constraints = mock_constraint_policy

        device_manager.device_list = [mock_device]

        # Act
        # Using global_defaults = 50.0 but constraint requires 60.0
        with patch("device_manager.ConfigManager.get_device_startup_frequency", return_value=50):
            await device_manager._apply_startup_frequency()

        # Assert
        mock_device.write_value.assert_called_once_with("RW_HZ", 60.0)

    async def test_when_no_startup_frequency_configured_then_skips_setting(self, device_manager, mock_device):
        """Test that when no startup frequency is configured, it skips writing"""
        # Arrange
        device_manager.device_list = [mock_device]

        # Act
        with patch("device_manager.ConfigManager.get_device_startup_frequency", return_value=None):
            await device_manager._apply_startup_frequency()

        # Assert
        mock_device.write_value.assert_not_called()

    async def test_when_device_write_fails_then_logs_error(self, device_manager, mock_device, caplog):
        """Test that when device write fails, an error is logged"""
        # Arrange
        device_manager.device_list = [mock_device]
        mock_device.write_value.side_effect = Exception("Write failed")

        # Act
        with patch("device_manager.ConfigManager.get_device_startup_frequency", return_value=56):
            with caplog.at_level(logging.WARNING):
                await device_manager._apply_startup_frequency()

        # Assert
        assert "Failed to set startup frequency" in caplog.text
        assert "Write failed" in caplog.text

    async def test_when_no_constraint_config_then_skips_startup_frequency_setup(self, caplog):
        """Test that when no constraint config is available, startup frequency setup is skipped"""
        # Arrange
        with patch("device_manager.ConfigManager") as mock_config_manager:
            mock_config_manager.return_value.load_yaml_file.return_value = {"devices": []}
            manager = AsyncDeviceManager(config_path="dummy_path", constraint_config_schema=None)
            manager.device_list = [Mock()]

            # Act
            with caplog.at_level(logging.WARNING):
                await manager._apply_startup_frequency()

        # Assert
        assert "No constraint config available" in caplog.text

    async def test_when_multiple_devices_then_processes_all_devices(self, device_manager):
        """Test that multiple devices are all processed"""
        # Arrange
        devices = []
        for i in range(3):
            mock_device = Mock(spec=AsyncGenericModbusDevice)
            mock_device.model = f"DEVICE_{i}"
            mock_device.slave_id = i
            mock_device.write_value = AsyncMock()

            mock_constraint_policy = Mock(spec=ConstraintPolicy)
            mock_constraint_policy.allow = Mock(return_value=True)
            mock_device.constraints = mock_constraint_policy

            devices.append(mock_device)

        device_manager.device_list = devices

        # Act
        with patch("device_manager.ConfigManager.get_device_startup_frequency", return_value=50):
            await device_manager._apply_startup_frequency()

        # Assert
        for device in devices:
            device.write_value.assert_called_once_with("RW_HZ", 50.0)

    async def test_when_constraint_policy_has_no_hz_constraint_then_sets_frequency_directly(self, device_manager):
        """Test that when no RW_HZ constraint exists, the frequency is written directly"""
        # Arrange
        mock_device = Mock(spec=AsyncGenericModbusDevice)
        mock_device.model = "DEVICE_NO_CONSTRAINT"
        mock_device.slave_id = 1
        mock_device.write_value = AsyncMock()

        # No RW_HZ constraint scenario
        mock_constraint_policy = Mock(spec=ConstraintPolicy)
        mock_constraint_policy.allow = Mock(return_value=True)
        mock_constraint_policy.constraints = {}
        mock_device.constraints = mock_constraint_policy

        device_manager.device_list = [mock_device]

        # Act
        with patch("device_manager.ConfigManager.get_device_startup_frequency", return_value=75.0):
            await device_manager._apply_startup_frequency()

        # Assert
        mock_device.write_value.assert_called_once_with("RW_HZ", 75.0)

    def test_when_checking_frequency_within_constraints_then_uses_constraint_policy(self, device_manager, mock_device):
        """Test that frequency checks delegate to the constraint policy"""
        # Arrange is handled by fixtures

        # Act
        result = device_manager._is_frequency_within_constraints(mock_device, 56.0)

        # Assert
        mock_device.constraints.allow.assert_called_once_with("RW_HZ", 56.0)
        assert result is True

    async def test_when_logging_warnings_for_corrected_frequency_then_includes_device_info(
        self, device_manager, caplog
    ):
        """Test that warning logs for corrected frequency include device info"""
        # Arrange
        mock_device = Mock(spec=AsyncGenericModbusDevice)
        mock_device.model = "TEST_DEVICE"
        mock_device.slave_id = 99
        mock_device.write_value = AsyncMock()

        # Reject original value, allow >= 40.0
        mock_constraint_policy = Mock(spec=ConstraintPolicy)
        mock_constraint_policy.allow = Mock(side_effect=lambda target, value: value >= 40.0)
        mock_constraint_policy.constraints = {"RW_HZ": ConstraintConfig(min=40.0, max=60.0)}
        mock_device.constraints = mock_constraint_policy

        device_manager.device_list = [mock_device]

        # Act
        with patch("device_manager.ConfigManager.get_device_startup_frequency", return_value=25.0):
            with caplog.at_level(logging.WARNING):
                await device_manager._apply_startup_frequency()

        # Assert
        assert "TEST_DEVICE_99" in caplog.text
        assert "outside constraints" in caplog.text
