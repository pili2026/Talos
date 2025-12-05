import pytest

from core.schema.control_condition_schema import ControlActionSchema, ControlActionType


class TestControlExecutorAdjustFrequency:
    """Test cases for ControlExecutor ADJUST_FREQUENCY functionality"""

    @pytest.fixture
    def adjust_frequency_action(self):
        """Create a basic ADJUST_FREQUENCY action for testing"""
        return ControlActionSchema(
            model="TECO_VFD",
            slave_id="2",
            type=ControlActionType.ADJUST_FREQUENCY,
            target="RW_HZ",
            value=2.5,  # +2.5 Hz adjustment
        )

    @pytest.mark.asyncio
    async def test_when_adjust_frequency_with_valid_params_then_calculates_and_writes_new_frequency(
        self, control_executor, mock_device_manager, mock_device, adjust_frequency_action
    ):
        """Test that ADJUST_FREQUENCY correctly reads current value, calculates new frequency, and writes it"""
        # Arrange
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = 45.0  # Current frequency: 45.0 Hz

        # Act
        await control_executor.execute([adjust_frequency_action])

        # Assert: new_freq = current_freq + adjustment = 45.0 + 2.5 = 47.5
        mock_device.read_value.assert_called_once_with("RW_HZ")
        mock_device.write_value.assert_called_once_with("RW_HZ", 47.5)

    @pytest.mark.asyncio
    async def test_when_adjust_frequency_with_negative_adjustment_then_decreases_frequency(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that ADJUST_FREQUENCY correctly handles negative adjustments (decrease frequency)"""
        # Arrange
        action = ControlActionSchema(
            model="TECO_VFD",
            slave_id="2",
            type=ControlActionType.ADJUST_FREQUENCY,
            target="RW_HZ",
            value=-3.0,  # -3.0 Hz adjustment
        )
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = 50.0  # Current frequency: 50.0 Hz

        # Act
        await control_executor.execute([action])

        # Assert: new_freq = 50.0 + (-3.0) = 47.0
        mock_device.write_value.assert_called_once_with("RW_HZ", 47.0)

    @pytest.mark.asyncio
    async def test_when_adjust_frequency_missing_target_then_skips_execution(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that ADJUST_FREQUENCY is skipped when target is None (explicit target required)"""
        # Arrange
        action = ControlActionSchema(
            model="TECO_VFD",
            slave_id="2",
            type=ControlActionType.ADJUST_FREQUENCY,
            target=None,  # Missing target - should skip
            value=2.5,
        )
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device

        # Act
        await control_executor.execute([action])

        # Assert: Should not read or write anything
        mock_device.read_value.assert_not_called()
        mock_device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_adjust_frequency_empty_target_then_skips_execution(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that ADJUST_FREQUENCY is skipped when target is empty string"""
        # Arrange
        action = ControlActionSchema(
            model="TECO_VFD",
            slave_id="2",
            type=ControlActionType.ADJUST_FREQUENCY,
            target="",  # Empty target - should skip
            value=2.5,
        )
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device

        # Act
        await control_executor.execute([action])

        # Assert: Should not read or write anything
        mock_device.read_value.assert_not_called()
        mock_device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_adjust_frequency_register_not_writable_then_skips_execution(
        self, control_executor, mock_device_manager, mock_device, adjust_frequency_action
    ):
        """Test that ADJUST_FREQUENCY is skipped when target register is not writable"""
        # Arrange
        mock_device.register_map = {"RW_HZ": {"writable": False}}  # Not writable
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device

        # Act
        await control_executor.execute([adjust_frequency_action])

        # Assert: Should not read or write anything
        mock_device.read_value.assert_not_called()
        mock_device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_adjust_frequency_missing_value_then_skips_execution(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that ADJUST_FREQUENCY is skipped when adjustment value is None"""
        # Arrange
        action = ControlActionSchema(
            model="TECO_VFD",
            slave_id="2",
            type=ControlActionType.ADJUST_FREQUENCY,
            target="RW_HZ",
            value=None,  # Missing adjustment value
        )
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device

        # Act
        await control_executor.execute([action])

        # Assert: Should not read or write anything
        mock_device.read_value.assert_not_called()
        mock_device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_adjust_frequency_adjustment_too_small_then_skips_execution(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that ADJUST_FREQUENCY is skipped when adjustment value is zero or below tolerance"""
        # Arrange
        action = ControlActionSchema(
            model="TECO_VFD",
            slave_id="2",
            type=ControlActionType.ADJUST_FREQUENCY,
            target="RW_HZ",
            value=0.0,  # Zero adjustment (should be skipped with <= condition)
        )
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device

        # Act
        await control_executor.execute([action])

        # Assert: Should not read or write anything (skipped due to zero adjustment)
        mock_device.read_value.assert_not_called()
        mock_device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_adjust_frequency_read_current_fails_then_skips_execution(
        self, control_executor, mock_device_manager, mock_device, adjust_frequency_action
    ):
        """Test that ADJUST_FREQUENCY is skipped when reading current frequency fails"""
        # Arrange
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.side_effect = Exception("Read failed")

        # Act
        await control_executor.execute([adjust_frequency_action])

        # Assert: Should try to read but not write anything
        mock_device.read_value.assert_called_once_with("RW_HZ")
        mock_device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_adjust_frequency_read_returns_none_then_skips_execution(
        self, control_executor, mock_device_manager, mock_device, adjust_frequency_action
    ):
        """Test that ADJUST_FREQUENCY is skipped when current frequency read returns None"""
        # Arrange
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = None  # Cannot read current frequency

        # Act
        await control_executor.execute([adjust_frequency_action])

        # Assert: Should try to read but not write anything
        mock_device.read_value.assert_called_once_with("RW_HZ")
        mock_device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_adjust_frequency_write_fails_then_logs_error(
        self, control_executor, mock_device_manager, mock_device, adjust_frequency_action
    ):
        """Test that ADJUST_FREQUENCY handles write failures gracefully"""
        # Arrange
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = 45.0
        mock_device.write_value.side_effect = Exception("Write failed")

        # Act - Should not raise exception
        await control_executor.execute([adjust_frequency_action])

        # Assert: Should try both read and write
        mock_device.read_value.assert_called_once_with("RW_HZ")
        mock_device.write_value.assert_called_once_with("RW_HZ", 47.5)

    @pytest.mark.asyncio
    async def test_when_adjust_frequency_nonexistent_register_then_skips_execution(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that ADJUST_FREQUENCY is skipped when target register doesn't exist"""
        # Arrange
        action = ControlActionSchema(
            model="TECO_VFD",
            slave_id="2",
            type=ControlActionType.ADJUST_FREQUENCY,
            target="NONEXISTENT_REG",  # Register doesn't exist
            value=2.5,
        )
        mock_device.register_map = {"RW_HZ": {"writable": True}}  # Only RW_HZ exists
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device

        # Act
        await control_executor.execute([action])

        # Assert: Should not read or write anything
        mock_device.read_value.assert_not_called()
        mock_device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_adjust_frequency_with_explicit_target_then_executes_normally(
        self, control_executor, mock_device_manager, mock_device
    ):
        """Test that ADJUST_FREQUENCY executes normally when target is explicitly specified"""
        # Arrange
        action = ControlActionSchema(
            model="TECO_VFD",
            slave_id="2",
            type=ControlActionType.ADJUST_FREQUENCY,
            target="RW_HZ",  # Explicit target specified
            value=1.5,
        )
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = 45.0  # Current frequency

        # Act
        await control_executor.execute([action])

        # Assert: Should read current value and write adjusted value
        mock_device.read_value.assert_called_once_with("RW_HZ")
        mock_device.write_value.assert_called_once_with("RW_HZ", 46.5)
