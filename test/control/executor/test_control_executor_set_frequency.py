from unittest.mock import Mock

import pytest

from core.schema.control_condition_schema import ControlActionSchema, ControlActionType


class TestControlExecutorSetFrequency:
    """Test SET_FREQUENCY functionality of ControlExecutor"""

    @pytest.mark.asyncio
    async def test_when_set_frequency_with_explicit_target_then_writes_value(
        self, control_executor, mock_device_manager, mock_device, set_frequency_action
    ):
        """Test that SET_FREQUENCY writes the specified frequency value"""
        # Arrange
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = 40.0  # Current frequency different from target

        # Act
        await control_executor.execute([set_frequency_action])

        # Assert
        mock_device.write_value.assert_called_once_with("RW_HZ", 50.0)

    @pytest.mark.asyncio
    async def test_when_set_frequency_uses_default_target_then_writes_to_rw_hz(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that SET_FREQUENCY uses default target RW_HZ when target is None"""
        # Arrange
        action = ControlActionSchema(
            model="TECO_VFD",
            slave_id="2",
            type=ControlActionType.SET_FREQUENCY,
            target=None,  # Will use default RW_HZ
            value=45.0,
        )
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = 30.0  # Different from target

        # Act
        await control_executor.execute([action])

        # Assert
        mock_device.write_value.assert_called_once_with("RW_HZ", 45.0)

    @pytest.mark.asyncio
    async def test_when_set_frequency_same_as_current_then_skips_write(
        self, control_executor, mock_device_manager, mock_device, set_frequency_action
    ):
        """Test that SET_FREQUENCY skips write when current value equals target value"""
        # Arrange
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = 50.0  # Same as target

        # Act
        await control_executor.execute([set_frequency_action])

        # Assert
        mock_device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_set_frequency_register_not_writable_then_skips_execution(
        self, control_executor, mock_device_manager, mock_device, set_frequency_action
    ):
        """Test that SET_FREQUENCY is skipped when target register is not writable"""
        # Arrange
        mock_device.register_map = {"RW_HZ": {"writable": False}}  # Not writable
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device

        # Act
        await control_executor.execute([set_frequency_action])

        # Assert
        mock_device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_set_frequency_register_not_exists_then_skips_execution(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that SET_FREQUENCY is skipped when target register doesn't exist"""
        # Arrange
        action = ControlActionSchema(
            model="TECO_VFD",
            slave_id="2",
            type=ControlActionType.SET_FREQUENCY,
            target="NONEXISTENT_REG",  # Register doesn't exist
            value=50.0,
        )
        mock_device.register_map = {"RW_HZ": {"writable": True}}  # Only RW_HZ exists
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device

        # Act
        await control_executor.execute([action])

        # Assert
        mock_device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_set_frequency_truly_missing_value_then_skips_execution(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that SET_FREQUENCY is skipped when value is truly None (using Mock)"""
        # Arrange - Use Mock to force None value since Pydantic converts None to default

        action = Mock(spec=ControlActionSchema)
        action.model = "TECO_VFD"
        action.slave_id = "2"
        action.type = ControlActionType.SET_FREQUENCY
        action.target = "RW_HZ"
        action.value = None  # This will stay None since it's a mock

        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device

        # Act
        await control_executor.execute([action])

        # Assert
        mock_device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_set_frequency_with_zero_value_then_executes_normally(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that SET_FREQUENCY with 0.0 value executes normally (since None gets converted to 0.0)"""
        # Arrange - This reflects the actual behavior when user sets value=None
        action = ControlActionSchema(
            model="TECO_VFD",
            slave_id="2",
            type=ControlActionType.SET_FREQUENCY,
            target="RW_HZ",
            value=None,  # Will be converted to 0.0 by Pydantic
        )
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = 50.0  # Different from 0.0

        # Act
        await control_executor.execute([action])

        # Assert: Should execute with converted value 0.0
        mock_device.write_value.assert_called_once_with("RW_HZ", 0.0)

    @pytest.mark.asyncio
    async def test_when_set_frequency_read_current_fails_then_writes_anyway(
        self, control_executor, mock_device_manager, mock_device, set_frequency_action
    ):
        """Test that SET_FREQUENCY writes even when read current value fails"""
        # Arrange
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.side_effect = Exception("Read failed")

        # Act
        await control_executor.execute([set_frequency_action])

        # Assert
        mock_device.write_value.assert_called_once_with("RW_HZ", 50.0)

    @pytest.mark.asyncio
    async def test_when_set_frequency_with_tolerance_check_then_compares_correctly(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that SET_FREQUENCY tolerance check works correctly for numeric values"""
        # Arrange - current value very close but not exactly equal
        action = ControlActionSchema(
            model="TECO_VFD", slave_id="2", type=ControlActionType.SET_FREQUENCY, target="RW_HZ", value=50.0
        )
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        # Since VALUE_TOLERANCE = 0.0, even tiny differences should trigger write
        mock_device.read_value.return_value = 50.0001  # Very close but different

        # Act
        await control_executor.execute([action])

        # Assert
        mock_device.write_value.assert_called_once_with("RW_HZ", 50.0)
