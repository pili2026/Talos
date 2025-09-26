import pytest


class TestControlExecutorTurnOnOff:
    """Test TURN_ON and TURN_OFF functionality of ControlExecutor"""

    @pytest.mark.asyncio
    async def test_when_turn_on_device_supports_on_off_then_writes_1(
        self, control_executor, mock_device_manager, mock_device, turn_on_action
    ):
        """Test that TURN_ON writes 1 to RW_ON_OFF register when device supports it"""
        # Arrange
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = 0  # Currently OFF

        # Act
        await control_executor.execute([turn_on_action])

        # Assert
        mock_device.write_on_off.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_when_turn_off_device_supports_on_off_then_writes_0(
        self, control_executor, mock_device_manager, mock_device, turn_off_action
    ):
        """Test that TURN_OFF writes 0 to RW_ON_OFF register when device supports it"""
        # Arrange
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = 1  # Currently ON

        # Act
        await control_executor.execute([turn_off_action])

        # Assert
        mock_device.write_on_off.assert_called_once_with(0)

    @pytest.mark.asyncio
    async def test_when_turn_on_device_does_not_support_on_off_then_skips_execution(
        self, control_executor, mock_device_manager, mock_device, turn_on_action
    ):
        """Test that TURN_ON is skipped when device doesn't support on/off"""
        # Arrange
        mock_device.supports_on_off.return_value = False  # No on/off support
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device

        # Act
        await control_executor.execute([turn_on_action])

        # Assert
        mock_device.write_on_off.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_turn_on_already_on_then_skips_write(
        self, control_executor, mock_device_manager, mock_device, turn_on_action
    ):
        """Test that TURN_ON skips write when device is already on"""
        # Arrange
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = 1  # Already ON

        # Act
        await control_executor.execute([turn_on_action])

        # Assert
        mock_device.write_on_off.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_turn_off_already_off_then_skips_write(
        self, control_executor, mock_device_manager, mock_device, turn_off_action
    ):
        """Test that TURN_OFF skips write when device is already off"""
        # Arrange
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = 0  # Already OFF

        # Act
        await control_executor.execute([turn_off_action])

        # Assert
        mock_device.write_on_off.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_turn_on_read_fails_then_writes_anyway(
        self, control_executor, mock_device_manager, mock_device, turn_on_action
    ):
        """Test that TURN_ON writes even when read current state fails"""
        # Arrange
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.side_effect = Exception("Read failed")

        # Act
        await control_executor.execute([turn_on_action])

        # Assert
        mock_device.write_on_off.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_when_turn_off_read_fails_then_writes_anyway(
        self, control_executor, mock_device_manager, mock_device, turn_off_action
    ):
        """Test that TURN_OFF writes even when read current state fails"""
        # Arrange
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.side_effect = Exception("Read failed")

        # Act
        await control_executor.execute([turn_off_action])

        # Assert
        mock_device.write_on_off.assert_called_once_with(0)

    @pytest.mark.asyncio
    async def test_when_turn_on_device_missing_supports_on_off_method_then_skips_execution(
        self, control_executor, mock_device_manager, mock_device, turn_on_action
    ):
        """Test that TURN_ON is skipped when device doesn't have supports_on_off method"""
        # Arrange
        del mock_device.supports_on_off  # Remove the method
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device

        # Act
        await control_executor.execute([turn_on_action])

        # Assert
        mock_device.write_on_off.assert_not_called()
