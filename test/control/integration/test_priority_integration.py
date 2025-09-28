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

    def test_when_incremental_and_absolute_conditions_triggered_then_incremental_wins_by_priority(
        self, control_evaluator
    ):
        """T2.1: INCREMENTAL (90) vs ABSOLUTE (85) - INCREMENTAL should win"""
        # Arrange: Trigger both conditions
        snapshot = {"AIn01": 35.0, "AIn02": 25.0}  # Trigger ABSOLUTE (>25) and INCREMENTAL  # Difference 10°C > 4°C
        model, slave_id = "SD400", "3"

        # Act
        actions = control_evaluator.evaluate(model, slave_id, snapshot)

        # Assert: Verify only one action is produced, and it is the higher priority INCREMENTAL
        assert len(actions) == 1
        action = actions[0]

        # INCREMENTAL should win (priority=90 > 85)
        assert action.type == ControlActionType.ADJUST_FREQUENCY
        assert action.value == 1.5

    def test_when_absolute_and_discrete_conditions_triggered_then_absolute_wins_by_priority(self, control_evaluator):
        """T2.2: ABSOLUTE (85) vs DISCRETE (80) - ABSOLUTE should win"""
        # Arrange: Trigger ABSOLUTE and DISCRETE, but not INCREMENTAL
        snapshot = {
            "AIn01": 42.0,  # Trigger DISCRETE (>40) and ABSOLUTE (>25)
            "AIn02": 40.0,  # Difference 2°C < 4°C，should not trigger INCREMENTAL
            "AIn03": 4.0,  # Trigger DISCRETE between condition
        }
        model, slave_id = "SD400", "3"

        # Act
        actions = control_evaluator.evaluate(model, slave_id, snapshot)

        # Assert: ABSOLUTE Should win (priority=85 > 80)
        assert len(actions) == 1
        action = actions[0]

        assert action.type == ControlActionType.SET_FREQUENCY
        # Calculate value: 40.0 + (42.0 - 25.0) * 1.2 = 40.0 + 20.4 = 60.4
        expected_frequency = 60.4
        assert action.value == expected_frequency

    def test_when_all_three_conditions_triggered_then_incremental_wins_by_highest_priority(self, control_evaluator):
        """T2.3: Triple Conflict - INCREMENTAL (90) should win"""
        # Arrange: Trigger ABSOLUTE and DISCRETE, but not INCREMENTAL
        snapshot = {
            "AIn01": 45.0,  # Trigger DISCRETE (>40)and ABSOLUTE (>25)
            "AIn02": 35.0,  # Difference 10°C，trigger INCREMENTAL
            "AIn03": 4.0,  # In Range 3.0~5.0，Trigger DISCRETE between
        }
        model, slave_id = "SD400", "3"

        # Act
        actions = control_evaluator.evaluate(model, slave_id, snapshot)

        # Assert: INCREMENTAL should win (highest priority 90)
        assert len(actions) == 1
        action = actions[0]

        assert action.type == ControlActionType.ADJUST_FREQUENCY
        assert action.value == 1.5
