"""
Device Control Integration Tests
Tests TURN_ON/TURN_OFF actions for TECO_VFD device control
"""

from unittest.mock import AsyncMock, Mock

import pytest
import yaml

from core.evaluator.control_evaluator import ControlEvaluator
from core.executor.control_executor import ControlExecutor
from core.schema.constraint_schema import ConstraintConfigSchema
from core.schema.control_condition_schema import ControlActionType
from core.schema.control_config_schema import ControlConfig


class TestDeviceControl:
    """Integration tests for Device ON/OFF control functionality"""

    @pytest.fixture
    def constraint_config_schema(self):
        return ConstraintConfigSchema(
            **{
                "LITEON_EVO6800": {
                    "default_constraints": {"RW_HZ": {"min": 30, "max": 55}},
                    "instances": {
                        "1": {"constraints": {"RW_HZ": {"min": 55, "max": 57}}},
                        "2": {"use_default_constraints": True},
                    },
                }
            }
        )

    @pytest.fixture
    def device_control_config_yaml(self):
        """Configuration with Device control only"""
        return """
version: "1.0.0"
SD400:
  default_controls: []
  instances:
    "3":
      use_default_controls: false
      controls:
        # High temperature turns ON inverter
        - name: "High Temperature Turn On Inverter"
          code: "HIGH_TEMP_VFD_ON"
          priority: 75
          composite:
            any:
              - type: threshold
                sources:
                  - AIn01
                operator: gt
                threshold: 40.0
          policy:
            type: discrete_setpoint
          actions:
            - model: TECO_VFD
              slave_id: "1"
              type: turn_on
              target: RW_ON_OFF

        # Low temperature turns OFF inverter
        - name: "Low Temperature Turn Off Inverter"
          code: "LOW_TEMP_VFD_OFF"
          priority: 95
          composite:
            any:
              - type: threshold
                sources:
                  - AIn01
                operator: lt
                threshold: 25.0
          policy:
            type: discrete_setpoint
          actions:
            - model: TECO_VFD
              slave_id: "1"
              type: turn_off
              target: RW_ON_OFF
"""

    @pytest.fixture
    def control_config(self, device_control_config_yaml):
        """Create ControlConfig for device control tests"""
        config_dict = yaml.safe_load(device_control_config_yaml)
        version = config_dict.pop("version", "1.0.0")
        return ControlConfig(version=version, root=config_dict)

    @pytest.fixture
    def control_evaluator(self, control_config, constraint_config_schema):
        """Create ControlEvaluator for device tests"""
        return ControlEvaluator(control_config, constraint_config_schema)

    @pytest.fixture
    def mock_teco_vfd_device(self):
        """Mock TECO_VFD device with proper ON/OFF capability"""
        mock_device = Mock()
        mock_device.model = "TECO_VFD"
        mock_device.slave_id = "1"
        mock_device.register_map = {
            "RW_ON_OFF": {"offset": 9473, "scale": 1, "readable": True, "writable": True},
            "RW_HZ": {"offset": 9474, "scale": 0.01, "readable": True, "writable": True},
            "RW_RESET": {"offset": 9473, "scale": 1, "writable": True},
        }
        # TECO_VFD supports on/off control
        mock_device.supports_on_off = Mock(return_value=True)
        # Use AsyncMock for async methods
        mock_device.read_value = AsyncMock(return_value=0)  # Current state: OFF
        mock_device.write_value = AsyncMock(return_value=None)
        mock_device.write_on_off = AsyncMock(return_value=None)
        return mock_device

    @pytest.fixture
    def mock_device_manager(self, mock_teco_vfd_device):
        """Mock device manager returning TECO_VFD device"""
        mock_manager = Mock()
        mock_manager.get_device_by_model_and_slave_id = Mock(return_value=mock_teco_vfd_device)
        return mock_manager

    @pytest.fixture
    def control_executor(self, mock_device_manager):
        """Create ControlExecutor with mocked TECO_VFD"""
        return ControlExecutor(mock_device_manager)

    # ================================
    # 1: High Temperature Device Turn ON
    # ================================

    @pytest.mark.asyncio
    async def test_when_high_temperature_detected_then_turn_on_inverter(
        self, control_evaluator, control_executor, mock_device_manager, mock_teco_vfd_device
    ):
        """1: High temperature (>40°C) should turn ON TECO_VFD inverter"""
        # Arrange: High temperature triggers inverter ON
        snapshot = {"AIn01": 45.0}  # > 40°C threshold
        model, slave_id = "SD400", "3"

        # Act: Evaluator generates action
        actions = control_evaluator.evaluate(model, slave_id, snapshot)

        # Assert: Verify action generation
        assert len(actions) == 1
        action = actions[0]

        assert action.model == "TECO_VFD"
        assert action.slave_id == "1"
        assert action.type == ControlActionType.TURN_ON
        assert action.target == "RW_ON_OFF"
        # Note: TURN_ON actions don't use the value field (set to None by validation)

        # Act: Executor executes action
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_teco_vfd_device
        mock_teco_vfd_device.read_value.return_value = 0  # Currently OFF

        await control_executor.execute([action])

        # Assert: Verify execution calls
        mock_device_manager.get_device_by_model_and_slave_id.assert_called_once_with("TECO_VFD", "1")
        mock_teco_vfd_device.read_value.assert_called_once_with("RW_ON_OFF")  # Check current state
        mock_teco_vfd_device.write_on_off.assert_called_once_with(1)  # Turn ON

    @pytest.mark.asyncio
    async def test_when_inverter_already_on_then_skip_redundant_write(
        self, control_evaluator, control_executor, mock_device_manager, mock_teco_vfd_device
    ):
        """1b: Should skip write if inverter is already ON"""
        # Arrange: Generate TURN_ON action
        snapshot = {"AIn01": 45.0}
        actions = control_evaluator.evaluate("SD400", "3", snapshot)
        assert len(actions) == 1
        assert actions[0].type == ControlActionType.TURN_ON

        # Act: Execute when device is already ON
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_teco_vfd_device
        mock_teco_vfd_device.read_value.return_value = 1  # Already ON

        await control_executor.execute(actions)

        # Assert: Should read current state but skip write
        mock_teco_vfd_device.read_value.assert_called_once_with("RW_ON_OFF")
        mock_teco_vfd_device.write_on_off.assert_not_called()  # Should skip

    # ================================
    # 2: Low Temperature Device Turn OFF
    # ================================

    @pytest.mark.asyncio
    async def test_when_low_temperature_detected_then_turn_off_inverter(
        self, control_evaluator, control_executor, mock_device_manager, mock_teco_vfd_device
    ):
        """2: Low temperature (<25°C) should turn OFF TECO_VFD inverter"""
        # Arrange: Low temperature triggers inverter OFF
        snapshot = {"AIn01": 20.0}  # < 25°C threshold
        model, slave_id = "SD400", "3"

        # Act: Evaluator generates action
        actions = control_evaluator.evaluate(model, slave_id, snapshot)

        # Assert: Verify action generation (should be highest priority=95)
        assert len(actions) == 1
        action = actions[0]

        assert action.model == "TECO_VFD"
        assert action.slave_id == "1"
        assert action.type == ControlActionType.TURN_OFF
        assert action.target == "RW_ON_OFF"

        # Act: Executor executes action
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_teco_vfd_device
        mock_teco_vfd_device.read_value.return_value = 1  # Currently ON

        await control_executor.execute([action])

        # Assert: Verify execution calls
        mock_device_manager.get_device_by_model_and_slave_id.assert_called_once_with("TECO_VFD", "1")
        mock_teco_vfd_device.read_value.assert_called_once_with("RW_ON_OFF")  # Check current state
        mock_teco_vfd_device.write_on_off.assert_called_once_with(0)  # Turn OFF

    @pytest.mark.asyncio
    async def test_when_inverter_already_off_then_skip_redundant_write(
        self, control_evaluator, control_executor, mock_device_manager, mock_teco_vfd_device
    ):
        """2b: Should skip write if inverter is already OFF"""
        # Arrange: Generate TURN_OFF action
        snapshot = {"AIn01": 20.0}
        actions = control_evaluator.evaluate("SD400", "3", snapshot)
        assert len(actions) == 1
        assert actions[0].type == ControlActionType.TURN_OFF

        # Act: Execute when device is already OFF
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_teco_vfd_device
        mock_teco_vfd_device.read_value.return_value = 0  # Already OFF

        await control_executor.execute(actions)

        # Assert: Should read current state but skip write
        mock_teco_vfd_device.read_value.assert_called_once_with("RW_ON_OFF")
        mock_teco_vfd_device.write_on_off.assert_not_called()  # Should skip

    # ================================
    # 3: Priority Between ON and OFF
    # ================================

    @pytest.mark.asyncio
    async def test_when_both_on_and_off_conditions_triggered_then_higher_priority_wins(self, control_evaluator):
        """3: When both ON and OFF conditions are met, higher priority should win"""
        # Arrange: Temperature that triggers both conditions
        # AIn01 = 22°C: triggers OFF (< 25°C, priority=95) but not ON (< 40°C)
        # This test verifies OFF wins due to higher priority
        snapshot = {"AIn01": 22.0}
        model, slave_id = "SD400", "3"

        # Act: Evaluator should choose highest priority
        actions = control_evaluator.evaluate(model, slave_id, snapshot)

        # Assert: Should get TURN_OFF (priority=95) over TURN_ON (priority=75)
        assert len(actions) == 1
        action = actions[0]
        assert action.type == ControlActionType.TURN_OFF  # Higher priority wins

    # ================================
    # 4: Error Handling and Edge Cases
    # ================================

    @pytest.mark.asyncio
    async def test_when_device_does_not_support_on_off_then_skip_execution(
        self, control_evaluator, control_executor, mock_device_manager
    ):
        """4: Should skip execution if device doesn't support ON/OFF"""
        # Arrange: Create device that doesn't support ON/OFF
        mock_device = Mock()
        mock_device.model = "TECO_VFD"
        mock_device.supports_on_off = Mock(return_value=False)  # No ON/OFF support
        mock_device.write_on_off = AsyncMock()

        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device

        # Generate TURN_ON action
        snapshot = {"AIn01": 45.0}
        actions = control_evaluator.evaluate("SD400", "3", snapshot)
        assert len(actions) == 1
        assert actions[0].type == ControlActionType.TURN_ON

        # Act: Execute with unsupported device
        await control_executor.execute(actions)

        # Assert: Should not attempt to write
        mock_device.write_on_off.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_read_on_off_state_fails_then_continue_with_write(
        self, control_evaluator, control_executor, mock_device_manager, mock_teco_vfd_device
    ):
        """4b: Should continue with write even if reading current state fails"""
        # Arrange: Make read_value fail
        mock_teco_vfd_device.read_value.side_effect = Exception("Read failed")
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_teco_vfd_device

        # Generate TURN_ON action
        snapshot = {"AIn01": 45.0}
        actions = control_evaluator.evaluate("SD400", "3", snapshot)

        # Act: Execute with read failure
        await control_executor.execute(actions)

        # Assert: Should attempt read, fail, but still write
        mock_teco_vfd_device.read_value.assert_called_once_with("RW_ON_OFF")
        mock_teco_vfd_device.write_on_off.assert_called_once_with(1)  # Still write ON

    @pytest.mark.asyncio
    async def test_when_normal_temperature_then_no_device_control_action(self, control_evaluator):
        """4c: Normal temperature should not trigger any device control"""
        # Arrange: Temperature in normal range (25°C <= temp <= 40°C)
        snapshot = {"AIn01": 30.0}  # Between thresholds
        model, slave_id = "SD400", "3"

        # Act: Evaluator should not generate device control actions
        actions = control_evaluator.evaluate(model, slave_id, snapshot)

        # Assert: No device control actions
        for action in actions:
            if action.model == "TECO_VFD" and action.slave_id == "1":
                pytest.fail(f"Device control action should not be triggered at 30°C: {action}")
