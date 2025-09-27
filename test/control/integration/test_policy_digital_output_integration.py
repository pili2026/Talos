"""
Digital Output Control Integration Tests
Tests WRITE_DO actions for IMA_C device control
"""

import pytest

from unittest.mock import Mock, AsyncMock
import yaml

from evaluator.control_evaluator import ControlEvaluator
from executor.control_executor import ControlExecutor
from schema.control_config_schema import ControlConfig
from model.control_model import ControlActionType


class TestDigitalOutputControl:
    """Integration tests for Digital Output control functionality"""

    @pytest.fixture
    def digital_output_config_yaml(self):
        """Configuration with Digital Output controls only"""
        return """
version: "1.0.0"
SD400:
  default_controls: []
  instances:
    "3":
      use_default_controls: false
      controls:
        # High temperature turns ON DOut01
        - name: "High Temperature Turn On DOut01"
          code: "HIGH_TEMP_DO01_ON"
          priority: 85
          composite:
            any:
              - type: threshold
                source: AIn01
                operator: gt
                threshold: 40.0
          policy:
            type: discrete_setpoint
          action:
            model: IMA_C
            slave_id: "5"
            type: write_do
            target: DOut01
            value: 1

        # Low temperature turns OFF DOut02  
        - name: "Low Temperature Turn Off DOut02"
          code: "LOW_TEMP_DO02_OFF"
          priority: 90
          composite:
            any:
              - type: threshold
                source: AIn01
                operator: lt
                threshold: 25.0
          policy:
            type: discrete_setpoint
          action:
            model: IMA_C
            slave_id: "5"
            type: write_do
            target: DOut02
            value: 0
"""

    @pytest.fixture
    def control_config(self, digital_output_config_yaml):
        """Create ControlConfig for DO tests"""
        config_dict = yaml.safe_load(digital_output_config_yaml)
        version = config_dict.pop("version", "1.0.0")
        return ControlConfig(version=version, root=config_dict)

    @pytest.fixture
    def control_evaluator(self, control_config):
        """Create ControlEvaluator for DO tests"""
        return ControlEvaluator(control_config)

    @pytest.fixture
    def mock_ima_c_device(self):
        """Mock IMA_C device with proper DO register mapping"""
        mock_device = Mock()
        mock_device.model = "IMA_C"
        mock_device.slave_id = "5"
        mock_device.register_map = {
            "DOut01": {"offset": 3, "bit": 0, "readable": True, "writable": True},
            "DOut02": {"offset": 3, "bit": 1, "readable": True, "writable": True},
            "DIn01": {"offset": 2, "bit": 0, "readable": True},
            "DIn02": {"offset": 2, "bit": 1, "readable": True},
        }
        # IMA_C does not support generic on/off
        mock_device.supports_on_off = Mock(return_value=False)
        # Use AsyncMock for async methods
        mock_device.read_value = AsyncMock(return_value=0)  # Current state: OFF
        mock_device.write_value = AsyncMock(return_value=None)
        return mock_device

    @pytest.fixture
    def mock_device_manager(self, mock_ima_c_device):
        """Mock device manager returning IMA_C device"""
        mock_manager = Mock()
        mock_manager.get_device_by_model_and_slave_id = Mock(return_value=mock_ima_c_device)
        return mock_manager

    @pytest.fixture
    def control_executor(self, mock_device_manager):
        """Create ControlExecutor with mocked IMA_C"""
        return ControlExecutor(mock_device_manager)

    # ================================
    # 1: High Temperature DO Control
    # ================================

    @pytest.mark.asyncio
    async def test_when_high_temperature_detected_then_turn_on_dout01(
        self, control_evaluator, control_executor, mock_device_manager, mock_ima_c_device
    ):
        """1: High temperature (>40°C) should turn ON DOut01"""
        # Arrange: High temperature triggers DOut01 ON
        snapshot = {"AIn01": 45.0}  # > 40°C threshold
        model, slave_id = "SD400", "3"

        # Act: Evaluator generates action
        actions = control_evaluator.evaluate(model, slave_id, snapshot)

        # Assert: Verify action generation
        assert len(actions) == 1
        action = actions[0]

        assert action.model == "IMA_C"
        assert action.slave_id == "5"
        assert action.type == ControlActionType.WRITE_DO
        assert action.target == "DOut01"
        assert action.value == 1  # Turn ON

        # Act: Executor executes action
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_ima_c_device

        await control_executor.execute([action])

        # Assert: Verify execution
        mock_device_manager.get_device_by_model_and_slave_id.assert_called_once_with("IMA_C", "5")
        mock_ima_c_device.write_value.assert_called_once_with("DOut01", 1)

    @pytest.mark.asyncio
    async def test_when_normal_temperature_then_no_dout01_action(self, control_evaluator):
        """1b: Normal temperature should not trigger DOut01 action"""
        # Arrange: Temperature below threshold
        snapshot = {"AIn01": 35.0}  # < 40°C threshold
        model, slave_id = "SD400", "3"

        # Act: Evaluator should not generate action for DOut01
        actions = control_evaluator.evaluate(model, slave_id, snapshot)

        # Assert: No DOut01 action (might have other actions with lower priority)
        if actions:
            # If any action exists, it shouldn't be DOut01 control
            for action in actions:
                if action.model == "IMA_C" and action.target == "DOut01":
                    pytest.fail("DOut01 action should not be triggered at 35°C")

    # ================================
    # 2: Low Temperature DO Control
    # ================================

    @pytest.mark.asyncio
    async def test_when_low_temperature_detected_then_turn_off_dout02(
        self, control_evaluator, control_executor, mock_device_manager, mock_ima_c_device
    ):
        """2: Low temperature (<25°C) should turn OFF DOut02"""
        # Arrange: Low temperature triggers DOut02 OFF
        snapshot = {"AIn01": 20.0}  # < 25°C threshold
        model, slave_id = "SD400", "3"

        # Act: Evaluator generates action
        actions = control_evaluator.evaluate(model, slave_id, snapshot)

        # Assert: Verify action generation (should be highest priority=90)
        assert len(actions) == 1
        action = actions[0]

        assert action.model == "IMA_C"
        assert action.slave_id == "5"
        assert action.type == ControlActionType.WRITE_DO
        assert action.target == "DOut02"
        assert action.value == 0  # Turn OFF

        # Act: Executor executes action
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_ima_c_device
        mock_ima_c_device.read_value.return_value = 1  # Currently ON

        await control_executor.execute([action])

        # Assert: Verify execution
        mock_device_manager.get_device_by_model_and_slave_id.assert_called_once_with("IMA_C", "5")
        mock_ima_c_device.write_value.assert_called_once_with("DOut02", 0)

    @pytest.mark.asyncio
    async def test_when_normal_temperature_then_no_dout02_action(self, control_evaluator):
        """2b: Normal temperature should not trigger DOut02 action"""
        # Arrange: Temperature above threshold
        snapshot = {"AIn01": 30.0}  # > 25°C threshold
        model, slave_id = "SD400", "3"

        # Act: Evaluator evaluates conditions
        actions = control_evaluator.evaluate(model, slave_id, snapshot)

        # Assert: No DOut02 action
        if actions:
            for action in actions:
                if action.model == "IMA_C" and action.target == "DOut02":
                    pytest.fail("DOut02 action should not be triggered at 30°C")

    # ================================
    # 3: Edge Cases and Error Handling
    # ================================

    @pytest.mark.asyncio
    async def test_when_dout_register_not_writable_then_skip_execution(
        self, control_evaluator, control_executor, mock_device_manager
    ):
        """3: Should skip execution if DO register is not writable"""
        # Arrange: Create device with non-writable DOut01
        mock_device = Mock()
        mock_device.model = "IMA_C"
        mock_device.register_map = {
            "DOut01": {"offset": 3, "bit": 0, "readable": True, "writable": False}  # Not writable
        }
        mock_device.write_value = AsyncMock()

        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device

        # Generate action
        snapshot = {"AIn01": 45.0}
        actions = control_evaluator.evaluate("SD400", "3", snapshot)
        assert len(actions) == 1

        # Act: Execute with non-writable register
        await control_executor.execute(actions)

        # Assert: Should not attempt to write
        mock_device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_dout_register_not_found_then_skip_execution(
        self, control_evaluator, control_executor, mock_device_manager
    ):
        """3b: Should skip execution if DO register doesn't exist"""
        # Arrange: Create device without DOut01 register
        mock_device = Mock()
        mock_device.model = "IMA_C"
        mock_device.register_map = {
            "DOut02": {"offset": 3, "bit": 1, "readable": True, "writable": True}
            # DOut01 missing
        }
        mock_device.write_value = AsyncMock()

        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device

        # Generate action for DOut01
        snapshot = {"AIn01": 45.0}
        actions = control_evaluator.evaluate("SD400", "3", snapshot)
        assert len(actions) == 1
        assert actions[0].target == "DOut01"

        # Act: Execute with missing register
        await control_executor.execute(actions)

        # Assert: Should not attempt to write
        mock_device.write_value.assert_not_called()
