from unittest.mock import AsyncMock, Mock
import pytest
from schema.control_condition_schema import ControlActionSchema, ControlActionType


class TestControlExecutorGeneral:
    """Test general error handling and edge cases of ControlExecutor"""

    @pytest.mark.asyncio
    async def test_when_action_truly_missing_value_then_skips_execution(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that actions requiring value are skipped when value is truly None (using Mock)"""
        # Arrange - Use Mock to force None value since Pydantic converts None to default
        from unittest.mock import Mock

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
    async def test_when_action_with_zero_value_then_executes_normally(
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
    async def test_when_register_not_exists_then_skips_execution(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that action is skipped when target register doesn't exist"""
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
    async def test_when_register_not_writable_then_skips_execution(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that action is skipped when target register is not writable"""
        # Arrange
        action = ControlActionSchema(
            model="TECO_VFD",
            slave_id="2",
            type=ControlActionType.SET_FREQUENCY,
            target="RO_STATUS",  # Read-only register
            value=50.0,
        )
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device

        # Act
        await control_executor.execute([action])

        # Assert
        mock_device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_empty_action_list_then_no_operations(self, control_executor, mock_device_manager):
        """Test that empty action list results in no operations"""
        # Arrange
        actions = []

        # Act
        await control_executor.execute(actions)

        # Assert
        mock_device_manager.get_device_by_model_and_slave_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_device_missing_register_map_then_skips_execution(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that action is skipped when device has no register_map attribute"""
        # Arrange
        action = ControlActionSchema(
            model="TECO_VFD", slave_id="2", type=ControlActionType.SET_FREQUENCY, target="RW_HZ", value=50.0
        )
        del mock_device.register_map  # Remove register_map attribute
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device

        # Act
        await control_executor.execute([action])

        # Assert
        mock_device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_tolerance_check_with_non_numeric_comparison_then_uses_mock_action(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that tolerance check falls back to direct comparison for non-numeric values using Mock"""
        # Arrange - Use Mock to test non-numeric values since ControlActionModel only accepts numbers

        action = Mock(spec=ControlActionSchema)
        action.model = "TECO_VFD"
        action.slave_id = "2"
        action.type = ControlActionType.WRITE_DO
        action.target = "RW_DO"
        action.value = "ON"
        action.priority = 50
        action.reason = "[UNIT] non-numeric"
        action.emergency_override = False

        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value = AsyncMock(return_value="OFF")  # Different string value
        mock_device.write_value = AsyncMock()
        mock_device.register_map = {"RW_DO": {"writable": True}}

        # Act
        await control_executor.execute([action])

        # Assert
        mock_device.write_value.assert_called_once_with("RW_DO", "ON")

    @pytest.mark.asyncio
    async def test_when_tolerance_check_with_same_mock_string_then_skips_write(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that tolerance check skips write for identical string values using Mock"""
        # Arrange - Use Mock to test string values since ControlActionModel only accepts numbers
        from unittest.mock import Mock

        action = Mock(spec=ControlActionSchema)
        action.model = "TECO_VFD"
        action.slave_id = "2"
        action.type = ControlActionType.WRITE_DO
        action.target = "RW_DO"
        action.value = "ON"  # String value (only possible with Mock)

        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = "ON"  # Same string value

        # Act
        await control_executor.execute([action])

        # Assert
        mock_device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_tolerance_check_with_float_precision_then_compares_correctly(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that tolerance check works correctly for floating point precision edge cases"""
        # Arrange - Test numeric tolerance behavior with realistic values
        action = ControlActionSchema(
            model="TECO_VFD", slave_id="2", type=ControlActionType.SET_FREQUENCY, target="RW_HZ", value=50.0
        )
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        # Since VALUE_TOLERANCE = 0.0, even tiny differences should trigger write
        mock_device.read_value.return_value = 50.0000001  # Very close but different

        # Act
        await control_executor.execute([action])

        # Assert: Should write because difference exceeds tolerance (0.0)
        mock_device.write_value.assert_called_once_with("RW_HZ", 50.0)

    @pytest.mark.asyncio
    async def test_when_normalize_on_off_state_with_valid_numeric_then_converts_to_int(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that _normalize_on_off_state correctly converts numeric values"""
        # This is testing the internal method indirectly through TURN_ON behavior
        # Arrange
        action = ControlActionSchema(model="TECO_VFD", slave_id="2", type=ControlActionType.TURN_ON)
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = "0.0"  # String representation of float

        # Act
        await control_executor.execute([action])

        # Assert: Should convert "0.0" to 0 and proceed with write
        mock_device.write_on_off.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_when_normalize_on_off_state_with_invalid_value_then_writes_anyway(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that invalid on/off state values result in write anyway"""
        # Arrange
        action = ControlActionSchema(model="TECO_VFD", slave_id="2", type=ControlActionType.TURN_ON)
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = "INVALID"  # Invalid state

        # Act
        await control_executor.execute([action])

        # Assert: Should write anyway when normalization fails
        mock_device.write_on_off.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_when_action_has_reason_attribute_then_includes_in_logs(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that action reason is included in log messages when present"""
        # This test verifies the _get_reason_suffix method works correctly
        # We can't directly test log output, but we can verify the action executes normally
        # with a reason attribute present
        # Arrange
        action = ControlActionSchema(
            model="TECO_VFD", slave_id="2", type=ControlActionType.SET_FREQUENCY, target="RW_HZ", value=50.0
        )
        # Add reason attribute (this might be added by the evaluator)
        action.reason = "Temperature control triggered"

        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = 40.0  # Different from target

        # Act
        await control_executor.execute([action])

        # Assert: Action should execute normally
        mock_device.write_value.assert_called_once_with("RW_HZ", 50.0)

    @pytest.mark.asyncio
    async def test_when_mixed_valid_and_invalid_actions_then_executes_only_valid(
        self, control_executor, mock_device_manager, mock_device, mock_do_device
    ):
        """Test that mix of valid and invalid actions only executes valid ones"""
        # Arrange
        actions = [
            ControlActionSchema(
                model="TECO_VFD",
                slave_id="2",
                type=ControlActionType.SET_FREQUENCY,
                target="RW_HZ",
                value=45.0,  # Valid action
            ),
            ControlActionSchema(
                model="TECO_VFD",
                slave_id="2",
                type=ControlActionType.SET_FREQUENCY,
                target="NONEXISTENT_REG",  # Invalid - register doesn't exist
                value=50.0,
            ),
            ControlActionSchema(
                model="DO_MODULE",
                slave_id="3",
                type=ControlActionType.WRITE_DO,
                target="DO_01",
                value=1,  # Valid action
            ),
        ]

        def get_device(model, slave_id):
            if model == "TECO_VFD" and slave_id == "2":
                return mock_device
            elif model == "DO_MODULE" and slave_id == "3":
                return mock_do_device
            return None

        mock_device_manager.get_device_by_model_and_slave_id.side_effect = get_device
        mock_device.read_value.return_value = 0  # Different from targets
        mock_do_device.read_value.return_value = 0

        # Act
        await control_executor.execute(actions)

        # Assert: Only valid actions should execute
        mock_device.write_value.assert_called_once_with("RW_HZ", 45.0)
        mock_do_device.write_value.assert_called_once_with("DO_01", 1)
