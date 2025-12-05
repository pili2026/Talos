from unittest.mock import Mock

import pytest

from core.schema.control_condition_schema import ControlActionSchema, ControlActionType


class TestControlExecutorReset:
    """Test RESET functionality of ControlExecutor"""

    @pytest.mark.asyncio
    async def test_when_reset_with_explicit_target_then_writes_value(
        self, control_executor, mock_device_manager, mock_device, reset_action
    ):
        """Test that RESET writes the specified value to target register"""
        # Arrange
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = 0  # Current value different from target

        # Act
        await control_executor.execute([reset_action])

        # Assert
        mock_device.write_value.assert_called_once_with("RW_RESET", 1)

    @pytest.mark.asyncio
    async def test_when_reset_uses_default_target_then_writes_to_rw_reset(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that RESET uses default target RW_RESET when target is None"""
        # Arrange
        action = ControlActionSchema(
            model="TECO_VFD",
            slave_id="2",
            type=ControlActionType.RESET,
            target=None,  # Will use default RW_RESET
            value=1,
        )
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = 0  # Different from target

        # Act
        await control_executor.execute([action])

        # Assert
        mock_device.write_value.assert_called_once_with("RW_RESET", 1)

    @pytest.mark.asyncio
    async def test_when_reset_same_as_current_then_skips_write(
        self, control_executor, mock_device_manager, mock_device, reset_action
    ):
        """Test that RESET skips write when current value equals target value"""
        # Arrange
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = 1  # Same as target

        # Act
        await control_executor.execute([reset_action])

        # Assert
        mock_device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_reset_register_not_writable_then_skips_execution(
        self, control_executor, mock_device_manager, mock_device, reset_action
    ):
        """Test that RESET is skipped when target register is not writable"""
        # Arrange
        mock_device.register_map = {"RW_RESET": {"writable": False}}  # Not writable
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device

        # Act
        await control_executor.execute([reset_action])

        # Assert
        mock_device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_reset_register_not_exists_then_skips_execution(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that RESET is skipped when target register doesn't exist"""
        # Arrange
        action = ControlActionSchema(
            model="TECO_VFD",
            slave_id="2",
            type=ControlActionType.RESET,
            target="NONEXISTENT_REG",  # Register doesn't exist
            value=1,
        )
        mock_device.register_map = {"RW_RESET": {"writable": True}}  # Only RW_RESET exists
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device

        # Act
        await control_executor.execute([action])

        # Assert
        mock_device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_reset_truly_missing_value_then_skips_execution(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that RESET is skipped when value is truly None (using Mock)"""
        # Arrange - Use Mock to force None value since Pydantic converts None to default

        action = Mock(spec=ControlActionSchema)
        action.model = "TECO_VFD"
        action.slave_id = "2"
        action.type = ControlActionType.RESET
        action.target = "RW_RESET"
        action.value = None  # This will stay None since it's a mock

        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device

        # Act
        await control_executor.execute([action])

        # Assert
        mock_device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_reset_with_zero_value_then_executes_normally(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that RESET with 0 value executes normally (since None gets converted to 0)"""
        # Arrange - This reflects the actual behavior when user sets value=None
        action = ControlActionSchema(
            model="TECO_VFD",
            slave_id="2",
            type=ControlActionType.RESET,
            target="RW_RESET",
            value=None,  # Will be converted to 0 by Pydantic
        )
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = 1  # Different from 0

        # Act
        await control_executor.execute([action])

        # Assert: Should execute with converted value 0
        mock_device.write_value.assert_called_once_with("RW_RESET", 0)

    @pytest.mark.asyncio
    async def test_when_reset_read_current_fails_then_writes_anyway(
        self, control_executor, mock_device_manager, mock_device, reset_action
    ):
        """Test that RESET writes even when read current value fails"""
        # Arrange
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.side_effect = Exception("Read failed")

        # Act
        await control_executor.execute([reset_action])

        # Assert
        mock_device.write_value.assert_called_once_with("RW_RESET", 1)

    @pytest.mark.asyncio
    async def test_when_reset_write_fails_then_logs_error(
        self, control_executor, mock_device_manager, mock_device, reset_action
    ):
        """Test that RESET handles write failures gracefully"""
        # Arrange
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = 0
        mock_device.write_value.side_effect = Exception("Write failed")

        # Act - Should not raise exception
        await control_executor.execute([reset_action])

        # Assert: Should attempt write despite failure
        mock_device.write_value.assert_called_once_with("RW_RESET", 1)

    @pytest.mark.asyncio
    async def test_when_reset_with_custom_value_then_writes_custom_value(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that RESET can write custom reset values (not just 1)"""
        # Arrange
        action = ControlActionSchema(
            model="TECO_VFD",
            slave_id="2",
            type=ControlActionType.RESET,
            target="RW_RESET",
            value=99,  # Custom reset value
        )
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = 0  # Different from target

        # Act
        await control_executor.execute([action])

        # Assert
        mock_device.write_value.assert_called_once_with("RW_RESET", 99)
