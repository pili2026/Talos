import pytest
from schema.control_condition_schema import ControlActionSchema, ControlActionType


class TestControlExecutorBasic:
    """Test basic infrastructure functionality of ControlExecutor"""

    @pytest.mark.asyncio
    async def test_when_action_missing_model_then_skips_execution(self, control_executor, mock_device_manager):
        """Test that action without model is skipped"""
        # Arrange
        action = ControlActionSchema(model="", slave_id="2", type=ControlActionType.TURN_ON)  # Missing model

        # Act
        await control_executor.execute([action])

        # Assert
        mock_device_manager.get_device_by_model_and_slave_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_action_missing_slave_id_then_skips_execution(self, control_executor, mock_device_manager):
        """Test that action without slave_id is skipped"""
        # Arrange
        action = ControlActionSchema(model="TECO_VFD", slave_id="", type=ControlActionType.TURN_ON)  # Missing slave_id

        # Act
        await control_executor.execute([action])

        # Assert
        mock_device_manager.get_device_by_model_and_slave_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_device_not_found_then_skips_execution(
        self, control_executor, mock_device_manager, turn_on_action
    ):
        """Test that action with non-existent device is skipped"""
        # Arrange
        mock_device_manager.get_device_by_model_and_slave_id.return_value = None  # Device not found

        # Act
        await control_executor.execute([turn_on_action])

        # Assert
        mock_device_manager.get_device_by_model_and_slave_id.assert_called_once_with("TECO_VFD", "2")

    @pytest.mark.asyncio
    async def test_when_multiple_actions_then_executes_all_valid_actions(
        self, control_executor, mock_device_manager, mock_device, mock_do_device
    ):
        """Test that multiple valid actions are all executed"""
        # Arrange
        actions = [
            ControlActionSchema(
                model="TECO_VFD", slave_id="2", type=ControlActionType.SET_FREQUENCY, target="RW_HZ", value=45.0
            ),
            ControlActionSchema(
                model="DO_MODULE", slave_id="3", type=ControlActionType.WRITE_DO, target="DO_01", value=1
            ),
        ]

        # Setup device manager to return appropriate devices
        def get_device(model, slave_id):
            if model == "TECO_VFD" and slave_id == "2":
                return mock_device
            elif model == "DO_MODULE" and slave_id == "3":
                return mock_do_device
            return None

        mock_device_manager.get_device_by_model_and_slave_id.side_effect = get_device
        mock_device.read_value.return_value = 0  # Different from target values
        mock_do_device.read_value.return_value = 0

        # Act
        await control_executor.execute(actions)

        # Assert: Both actions should be executed
        mock_device.write_value.assert_called_once_with("RW_HZ", 45.0)
        mock_do_device.write_value.assert_called_once_with("DO_01", 1)

    @pytest.mark.asyncio
    async def test_when_exception_in_action_then_continues_with_next_action(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that exception in one action doesn't stop execution of subsequent actions"""
        # Arrange
        actions = [
            ControlActionSchema(
                model="TECO_VFD", slave_id="2", type=ControlActionType.SET_FREQUENCY, target="RW_HZ", value=45.0
            ),
            ControlActionSchema(
                model="TECO_VFD", slave_id="2", type=ControlActionType.SET_FREQUENCY, target="RW_HZ", value=50.0
            ),
        ]
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = 0

        # Make first write fail, second should still execute
        mock_device.write_value.side_effect = [Exception("First write failed"), None]

        # Act - Should not raise exception
        await control_executor.execute(actions)

        # Assert: Both writes should be attempted despite first one failing
        assert mock_device.write_value.call_count == 2
