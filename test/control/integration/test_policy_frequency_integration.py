"""
Integration Tests for Control System - Core Tests (T1-T3)
Tests the complete flow: Config → ControlEvaluator → ControlExecutor
"""

from unittest.mock import AsyncMock, Mock

import pytest
import yaml

from core.evaluator.control_evaluator import ControlEvaluator
from core.executor.control_executor import ControlExecutor
from core.schema.constraint_schema import ConstraintConfigSchema
from core.schema.control_condition_schema import ControlActionSchema, ControlActionType
from core.schema.control_config_schema import ControlConfig


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
          priority: 12
          composite:
            any:
              - sources_id: high_temp_ain01
                type: threshold
                sources:
                  - device: SD400
                    slave_id: "3"
                    pins: [AIn01]
                operator: gt
                threshold: 40.0
                hysteresis: 1.0
                debounce_sec: 0.5

              - sources_id: high_temp_ain03
                type: threshold
                sources:
                  - device: SD400
                    slave_id: "3"
                    pins: [AIn03]
                operator: between
                min: 3.0
                max: 5.0
                hysteresis: 0.2
          policy:
            type: discrete_setpoint
          actions:
            - model: TECO_VFD
              slave_id: "2"
              type: set_frequency
              target: RW_HZ
              value: 45.0

        # ABSOLUTE_LINEAR - Single temperature mapping
        - name: "Environment Temperature Linear Control"
          code: "LIN_ABS01"
          priority: 11
          composite:
            any:
              - sources_id: lin_abs_temp
                type: threshold
                sources:
                  - device: SD400
                    slave_id: "3"
                    pins: [AIn01]
                operator: gt
                threshold: 25.0
                abs: false
          policy:
            type: absolute_linear
            input_sources_id: lin_abs_temp
            base_freq: 40.0
            base_temp: 25.0
            gain_hz_per_unit: 1.2
          actions:
            - model: TECO_VFD
              slave_id: "2"
              type: set_frequency
              target: RW_HZ

        # INCREMENTAL_LINEAR - Temperature difference adjustment
        - name: "Supply-Return Temperature Difference Control"
          code: "LIN_INC01"
          priority: 10
          composite:
            any:
              - sources_id: lin_inc_diff_pos
                type: difference
                sources:
                  - device: SD400
                    slave_id: "3"
                    pins: [AIn01]
                  - device: SD400
                    slave_id: "3"
                    pins: [AIn02]
                operator: gt
                threshold: 4.0
                abs: false

              - sources_id: lin_inc_diff_neg
                type: difference
                sources:
                  - device: SD400
                    slave_id: "3"
                    pins: [AIn01]
                  - device: SD400
                    slave_id: "3"
                    pins: [AIn02]
                operator: lt
                threshold: -4.0
                abs: false
          policy:
            type: incremental_linear
            input_sources_id: lin_inc_diff_pos
            gain_hz_per_unit: 1.5
          actions:
            - model: TECO_VFD
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
        """Mock AsyncGenericModbusDevice"""
        mock_device = Mock()
        mock_device.model = "TECO_VFD"
        mock_device.slave_id = "2"
        mock_device.register_map = {
            "RW_HZ": {"writable": True, "address": 8193},
            "RW_ON_OFF": {"writable": True, "address": 8192},
        }

        mock_device.read_value = AsyncMock(return_value=50.0)
        mock_device.write_value = AsyncMock(return_value=None)
        mock_device.write_on_off = AsyncMock(return_value=None)
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
        snapshot = {"AIn03": 4.0}
        model, slave_id = "SD400", "3"

        # Act
        actions = control_evaluator.evaluate(model, slave_id, snapshot)

        # Assert
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

        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        await control_executor.execute([action])

        mock_device_manager.get_device_by_model_and_slave_id.assert_called_once_with("TECO_VFD", "2")
        mock_device.write_value.assert_called_once_with("RW_HZ", 45.0)

    @pytest.mark.asyncio
    async def test_when_absolute_linear_condition_triggered_then_calculates_linear_frequency(
        self, control_evaluator, control_executor, mock_device_manager, mock_device
    ):
        """T1.2: ABSOLUTE_LINEAR"""
        snapshot = {"AIn01": 30.0, "AIn02": 28.0}
        model, slave_id = "SD400", "3"

        # Act
        actions = control_evaluator.evaluate(model, slave_id, snapshot)

        # Assert
        assert len(actions) == 1
        action = actions[0]

        # Expected: 40.0 + (30.0 - 25.0) * 1.2 = 46.0
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

        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        await control_executor.execute([action])

        mock_device.write_value.assert_called_once_with("RW_HZ", 46.0)

    @pytest.mark.asyncio
    async def test_when_incremental_linear_condition_triggered_then_adjusts_frequency_by_difference(
        self, control_evaluator, control_executor, mock_device_manager, mock_device
    ):
        """T1.3: INCREMENTAL_LINEAR"""
        snapshot = {"AIn01": 35.0, "AIn02": 25.0}
        model, slave_id = "SD400", "3"

        # Act
        actions = control_evaluator.evaluate(model, slave_id, snapshot)

        # Assert
        assert len(actions) == 2
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

        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device
        mock_device.read_value.return_value = 50.0

        await control_executor.execute([action])

        mock_device.read_value.assert_called_once_with("RW_HZ")
        expected_new_freq = 50.0 + 1.5
        mock_device.write_value.assert_called_once_with("RW_HZ", expected_new_freq)

    def _verify_action_properties(self, action: ControlActionSchema, expected_props: dict):
        """Helper to verify action properties"""
        for prop, expected_value in expected_props.items():
            actual_value = getattr(action, prop)
            assert actual_value == expected_value, f"Expected {prop}={expected_value}, got {actual_value}"
