from unittest.mock import Mock
import pytest
from schema.control_condition_schema import ControlActionSchema, ControlActionType


class TestControlExecutorWriteDO:
    """Test WRITE_DO functionality of ControlExecutor"""

    @pytest.mark.asyncio
    async def test_when_write_do_with_explicit_target_then_writes_value(
        self, control_executor, mock_device_manager, mock_do_device, write_do_action
    ):
        """Test that WRITE_DO writes the specified value to target digital output pin"""
        # Arrange
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_do_device
        mock_do_device.read_value.return_value = 0  # Current value different from target

        # Act
        await control_executor.execute([write_do_action])

        # Assert
        mock_device_manager.get_device_by_model_and_slave_id.assert_called_once_with("DO_MODULE", "3")
        mock_do_device.write_value.assert_called_once_with("DO_01", 1)

    @pytest.mark.asyncio
    async def test_when_write_do_uses_default_target_then_writes_to_rw_do(
        self, control_executor, mock_device_manager, mock_do_device
    ):
        """Test that WRITE_DO uses default target RW_DO when target is None"""
        # Arrange
        action = ControlActionSchema(
            model="DO_MODULE",
            slave_id="3",
            type=ControlActionType.WRITE_DO,
            target=None,  # Will use default RW_DO
            value=1,
        )
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_do_device
        mock_do_device.read_value.return_value = 0  # Different from target

        # Act
        await control_executor.execute([action])

        # Assert
        mock_device_manager.get_device_by_model_and_slave_id.assert_called_once_with("DO_MODULE", "3")
        mock_do_device.write_value.assert_called_once_with("RW_DO", 1)

    @pytest.mark.asyncio
    async def test_when_write_do_same_as_current_then_skips_write(
        self, control_executor, mock_device_manager, mock_do_device, write_do_action
    ):
        """Test that WRITE_DO skips write when current value equals target value"""
        # Arrange
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_do_device
        mock_do_device.read_value.return_value = 1  # Same as target

        # Act
        await control_executor.execute([write_do_action])

        # Assert
        mock_do_device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_write_do_register_not_writable_then_skips_execution(
        self, control_executor, mock_device_manager, mock_do_device, write_do_action
    ):
        """Test that WRITE_DO is skipped when target register is not writable"""
        # Arrange
        mock_do_device.register_map = {"DO_01": {"writable": False}}  # Not writable
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_do_device

        # Act
        await control_executor.execute([write_do_action])

        # Assert
        mock_do_device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_write_do_register_not_exists_then_skips_execution(
        self, control_executor, mock_device_manager, mock_do_device
    ):
        """Test that WRITE_DO is skipped when target register doesn't exist"""
        # Arrange
        action = ControlActionSchema(
            model="DO_MODULE",
            slave_id="3",
            type=ControlActionType.WRITE_DO,
            target="NONEXISTENT_DO",  # Register doesn't exist
            value=1,
        )
        mock_do_device.register_map = {"DO_01": {"writable": True}}  # Only DO_01 exists
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_do_device

        # Act
        await control_executor.execute([action])

        # Assert
        mock_do_device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_write_do_truly_missing_value_then_skips_execution(
        self, control_executor, mock_device_manager, mock_do_device
    ):
        """Test that WRITE_DO is skipped when value is truly None (using Mock)"""
        # Arrange - Use Mock to force None value since Pydantic converts None to default

        action = Mock(spec=ControlActionSchema)
        action.model = "DO_MODULE"
        action.slave_id = "3"
        action.type = ControlActionType.WRITE_DO
        action.target = "DO_01"
        action.value = None  # This will stay None since it's a mock

        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_do_device

        # Act
        await control_executor.execute([action])

        # Assert
        mock_do_device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_write_do_with_zero_value_then_executes_normally(
        self, control_executor, mock_device_manager, mock_do_device
    ):
        """Test that WRITE_DO with 0 value executes normally (since None gets converted to 0)"""
        # Arrange - This reflects the actual behavior when user sets value=None
        action = ControlActionSchema(
            model="DO_MODULE",
            slave_id="3",
            type=ControlActionType.WRITE_DO,
            target="DO_01",
            value=None,  # Will be converted to 0 by Pydantic
        )
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_do_device
        mock_do_device.read_value.return_value = 1  # Different from 0

        # Act
        await control_executor.execute([action])

        # Assert: Should execute with converted value 0
        mock_device_manager.get_device_by_model_and_slave_id.assert_called_once_with("DO_MODULE", "3")
        mock_do_device.write_value.assert_called_once_with("DO_01", 0)

    @pytest.mark.asyncio
    async def test_when_write_do_read_current_fails_then_writes_anyway(
        self, control_executor, mock_device_manager, mock_do_device, write_do_action
    ):
        """Test that WRITE_DO writes even when read current value fails"""
        # Arrange
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_do_device
        mock_do_device.read_value.side_effect = Exception("Read failed")

        # Act
        await control_executor.execute([write_do_action])

        # Assert
        mock_do_device.write_value.assert_called_once_with("DO_01", 1)

    @pytest.mark.asyncio
    async def test_when_write_do_multiple_pins_then_writes_to_correct_pins(
        self, control_executor, mock_device_manager, mock_do_device
    ):
        """Test that WRITE_DO can control multiple digital output pins"""
        # Arrange
        actions = [
            ControlActionSchema(
                model="DO_MODULE", slave_id="3", type=ControlActionType.WRITE_DO, target="DO_01", value=1
            ),
            ControlActionSchema(
                model="DO_MODULE", slave_id="3", type=ControlActionType.WRITE_DO, target="DO_02", value=0
            ),
        ]
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_do_device
        # Setup different return values for different pin reads
        # DO_01 currently 0 (will write 1), DO_02 currently 1 (will write 0)
        mock_do_device.read_value.side_effect = [0, 1]  # First call returns 0, second returns 1

        # Act
        await control_executor.execute(actions)

        # Assert: Both pins should be written to
        assert mock_do_device.write_value.call_count == 2
        mock_do_device.write_value.assert_any_call("DO_01", 1)
        mock_do_device.write_value.assert_any_call("DO_02", 0)

    @pytest.mark.asyncio
    async def test_when_write_do_write_fails_then_logs_error(
        self, control_executor, mock_device_manager, mock_do_device, write_do_action
    ):
        """Test that WRITE_DO handles write failures gracefully"""
        # Arrange
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_do_device
        mock_do_device.read_value.return_value = 0
        mock_do_device.write_value.side_effect = Exception("Write failed")

        # Act - Should not raise exception
        await control_executor.execute([write_do_action])

        # Assert: Should attempt write despite failure
        mock_do_device.write_value.assert_called_once_with("DO_01", 1)
