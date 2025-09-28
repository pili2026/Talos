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
from schema.control_config_schema import ControlConfig
from model.control_model import ControlActionModel

from model.control_model import ControlActionType


class TestControlIntegration:
    """Integration tests for the complete control flow"""

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
    def control_evaluator(self, control_config):
        """Create ControlEvaluator with test configuration"""
        return ControlEvaluator(control_config)

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

    # ================================
    #  T1: Three Policy Basic Functionality Tests
    # ================================

    @pytest.mark.asyncio
    async def test_when_discrete_setpoint_condition_triggered_then_sets_fixed_frequency(
        self, control_evaluator, control_executor, mock_device_manager, mock_device
    ):
        """T1.1: DISCRETE_SETPOINT"""
        # Arrange: Trigger HIGH_TEMP but avoid triggering other conditions
        # HIGH_TEMP: AIn01 > 40.0 (priority=80)
        # LIN_ABS01: AIn01 > 25.0 (priority=85) ← must avoid triggering this
        # Solution: Use AIn03 between condition to trigger DISCRETE

        snapshot = {"AIn03": 4.0}  # Trigger between 3.0~5.0, avoid triggering other conditions
        model, slave_id = "SD400", "3"

        # Act: Evaluator generates action
        actions = control_evaluator.evaluate(model, slave_id, snapshot)

        # Assert: Verify generated action
        assert len(actions) == 1
        action = actions[0]

        self._verify_action_properties(
            action,
            {
                "model": "TECO_VFD",
                "slave_id": "2",
                "type": ControlActionType.SET_FREQUENCY,
                "target": "RW_HZ",
                "value": 45.0,
            },
        )

        # Act: Executor executes action (using async execute method)
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device

        await control_executor.execute([action])  # Pass in action list

        # Assert: Verify execution result
        mock_device_manager.get_device_by_model_and_slave_id.assert_called_once_with("TECO_VFD", "2")
        mock_device.write_value.assert_called_once_with("RW_HZ", 45.0)

    @pytest.mark.asyncio
    async def test_when_absolute_linear_condition_triggered_then_calculates_linear_frequency(
        self, control_evaluator, control_executor, mock_device_manager, mock_device
    ):
        """T1.2: ABSOLUTE_LINEAR - Linear calculation"""
        # Arrange: Trigger LIN_ABS01 but avoid triggering INCREMENTAL
        # LIN_ABS01: AIn01 > 25.0 (priority=85)
        # LIN_INC01: |AIn01-AIn02| > 4.0 (priority=90) ← must avoid triggering this
        snapshot = {"AIn01": 30.0, "AIn02": 28.0}  # Difference 2°C < 4°C，not triggering INCREMENTAL
        model, slave_id = "SD400", "3"

        # Act: Evaluator generates action
        actions = control_evaluator.evaluate(model, slave_id, snapshot)

        # Assert: Verify calculation result
        assert len(actions) == 1
        action = actions[0]

        # Expected value calculation: base_freq + (temp - base_temp) * gain
        # 40.0 + (30.0 - 25.0) * 1.2 = 40.0 + 6.0 = 46.0
        expected_frequency = 46.0

        self._verify_action_properties(
            action,
            {
                "model": "TECO_VFD",
                "slave_id": "2",
                "type": ControlActionType.SET_FREQUENCY,
                "target": "RW_HZ",
                "value": expected_frequency,
            },
        )

        # Act: Executor executes action
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device

        await control_executor.execute([action])

        # Assert: Verify execution result
        mock_device.write_value.assert_called_once_with("RW_HZ", 46.0)

    @pytest.mark.asyncio
    async def test_when_incremental_linear_condition_triggered_then_adjusts_frequency_by_difference(
        self, control_evaluator, control_executor, mock_device_manager, mock_device
    ):
        """T1.3: INCREMENTAL_LINEAR - Incremental adjustment"""
        # Arrange: Trigger LIN_INC01 (highest priority, overrides others)
        snapshot = {"AIn01": 35.0, "AIn02": 25.0}  # Difference 10°C > 4°C
        model, slave_id = "SD400", "3"

        # Act
        actions = control_evaluator.evaluate(model, slave_id, snapshot)

        # Assert:
        assert len(actions) == 1
        action = actions[0]

        expected_adjustment = 1.5

        self._verify_action_properties(
            action,
            {
                "model": "TECO_VFD",
                "slave_id": "2",
                "type": ControlActionType.ADJUST_FREQUENCY,
                "target": "RW_HZ",
                "value": expected_adjustment,
            },
        )

        # Act: Executor executes action (ADJUST_FREQUENCY needs to read current value first)
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = 50.0  # Currently frequency 50.0 Hz

        await control_executor.execute([action])

        # Assert: Verify calculation result
        mock_device.read_value.assert_called_once_with("RW_HZ")  # Read current value
        expected_new_freq = 50.0 + 1.5
        mock_device.write_value.assert_called_once_with("RW_HZ", expected_new_freq)

    def _verify_action_properties(self, action: ControlActionModel, expected_props: dict):
        """Helper to verify action properties"""
        for prop, expected_value in expected_props.items():
            actual_value = getattr(action, prop)
            assert actual_value == expected_value, f"Expected {prop}={expected_value}, got {actual_value}"
