"""
Integration Tests for Control System - Core Tests (T1-T3)
Tests the complete flow: Config → ControlEvaluator → ControlExecutor
"""

import pytest
import sys
import os
from unittest.mock import Mock, AsyncMock

import yaml

from evaluator.control_evaluator import ControlEvaluator
from executor.control_executor import ControlExecutor
from schema.constraint_schema import ConstraintConfigSchema
from schema.control_config_schema import ControlConfig
from model.control_model import ControlActionModel

from model.control_model import ControlActionType


class TestControlIntegration:
    """Integration tests for the complete control flow"""

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
    def sample_config_yaml(self):
        """Sample YAML configuration based on user's actual config"""
        return """
version: "1.0.0"
SD400:
  default_controls: []
  instances:
    "3":
      use_default_controls: false
      controls:
        # DISCRETE_SETPOINT - Fixed value control
        - name: "High Temperature Shutdown"
          code: "HIGH_TEMP"
          priority: 80
          composite:
            any:
              - type: threshold
                source: AIn01
                operator: gt
                threshold: 40.0
                hysteresis: 1.0
                debounce_sec: 0.5
              - type: threshold
                source: AIn03
                operator: between
                min: 3.0
                max: 5.0
                hysteresis: 0.2
          policy:
            type: discrete_setpoint
          action:
            model: TECO_VFD
            slave_id: "2"
            type: set_frequency
            target: RW_HZ
            value: 45.0

        # ABSOLUTE_LINEAR - Single temperature mapping
        - name: "Environment Temperature Linear Control"
          code: "LIN_ABS01"
          priority: 85
          composite:
            any:
              - type: threshold
                source: AIn01
                operator: gt
                threshold: 25.0
                abs: false
          policy:
            type: absolute_linear
            condition_type: threshold
            source: AIn01
            base_freq: 40.0
            base_temp: 25.0
            gain_hz_per_unit: 1.2
          action:
            model: TECO_VFD
            slave_id: "2"
            type: set_frequency
            target: RW_HZ

        # INCREMENTAL_LINEAR - Temperature difference adjustment
        - name: "Supply-Return Temperature Difference Control"
          code: "LIN_INC01"
          priority: 90
          composite:
            any:
              - type: difference
                sources: [AIn01, AIn02]
                operator: gt
                threshold: 4.0
                abs: false
              - type: difference
                sources: [AIn01, AIn02]
                operator: lt
                threshold: -4.0
                abs: false
          policy:
            type: incremental_linear
            condition_type: difference
            sources: [AIn01, AIn02]
            gain_hz_per_unit: 1.5
          action:
            model: TECO_VFD
            slave_id: "2"
            type: adjust_frequency
            target: RW_HZ
"""

    @pytest.fixture
    def control_config(self, sample_config_yaml):
        """Create ControlConfig from YAML"""
        config_dict = yaml.safe_load(sample_config_yaml)
        version = config_dict.pop("version", "1.0.0")
        return ControlConfig(version=version, root=config_dict)

    @pytest.fixture
    def control_evaluator(self, control_config, constraint_config_schema):
        """Create ControlEvaluator with test configuration"""
        return ControlEvaluator(control_config, constraint_config_schema)

    @pytest.fixture
    def mock_device(self):
        """Mock AsyncGenericModbusDevice with proper AsyncMock for async methods"""
        mock_device = Mock()
        mock_device.model = "TECO_VFD"
        mock_device.slave_id = "2"
        mock_device.register_map = {
            "RW_HZ": {"writable": True, "address": 8193},
            "RW_ON_OFF": {"writable": True, "address": 8192},
        }

        mock_device.read_value = AsyncMock(return_value=50.0)  # Current frequency 50.0 Hz
        mock_device.write_value = AsyncMock(return_value=None)
        mock_device.write_on_off = AsyncMock(return_value=None)
        # Keep Mock for synchronous methods
        mock_device.supports_on_off = Mock(return_value=True)
        return mock_device

    @pytest.fixture
    def mock_device_manager(self, mock_device):
        """Mock AsyncDeviceManager"""
        mock_manager = Mock()
        mock_manager.get_device_by_model_and_slave_id = Mock(return_value=mock_device)
        return mock_manager

    @pytest.fixture
    def control_executor(self, mock_device_manager):
        """Create ControlExecutor with mocked dependencies"""
        return ControlExecutor(mock_device_manager)

    @pytest.mark.asyncio
    async def test_when_complete_flow_executed_then_evaluator_and_executor_work_together(
        self, sample_config_yaml, constraint_config_schema, mock_device_manager, mock_device
    ):
        """T3: Complete end-to-end flow test"""
        # Step 1: Load configuration
        config_dict = yaml.safe_load(sample_config_yaml)
        version = config_dict.pop("version", "1.0.0")
        control_config = ControlConfig(version=version, root=config_dict)

        # Step 2: Create components
        evaluator = ControlEvaluator(control_config, constraint_config_schema)
        executor = ControlExecutor(mock_device_manager)

        # Step 3: Test scenario - INCREMENTAL triggered
        snapshot = {"AIn01": 38.0, "AIn02": 25.0}  # Difference 13°C
        model, slave_id = "SD400", "3"

        # Step 4: Evaluate and generate action
        actions = evaluator.evaluate(model, slave_id, snapshot)
        assert len(actions) == 1

        action = actions[0]
        assert action.type == ControlActionType.ADJUST_FREQUENCY
        expected_value = 1.5
        assert action.value == expected_value

        # Step 5: Execute action
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = 50.0  # Current frequency 50.0 Hz

        await executor.execute([action])

        # Step 6: Verify end-to-end flow
        mock_device_manager.get_device_by_model_and_slave_id.assert_called_once_with("TECO_VFD", "2")
        mock_device.read_value.assert_called_once_with("RW_HZ")

        expected_new_freq = 50.0 + expected_value
        mock_device.write_value.assert_called_once_with("RW_HZ", expected_new_freq)

    def test_when_no_conditions_triggered_then_returns_empty_actions(self, control_evaluator):
        """T3: Test scenario - No conditions triggered"""
        # Arrange: All conditions are not met
        snapshot = {
            "AIn01": 20.0,  # < 25°C (ABSOLUTE) And < 40°C (DISCRETE)
            "AIn02": 18.0,  # Difference 2°C < 4°C (INCREMENTAL)
            "AIn03": 2.0,  # < 3.0 (DISCRETE between)
        }
        model, slave_id = "SD400", "3"

        # Act
        actions = control_evaluator.evaluate(model, slave_id, snapshot)

        # Assert: Should be no action
        assert len(actions) == 0
