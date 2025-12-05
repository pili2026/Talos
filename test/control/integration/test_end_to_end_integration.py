from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from core.evaluator.control_evaluator import ControlEvaluator
from core.executor.control_executor import ControlExecutor
from core.model.enum.condition_enum import ControlActionType
from core.schema.constraint_schema import ConstraintConfigSchema
from core.schema.control_config_schema import ControlConfig


class TestEndToEndIntegration:
    """End-to-end integration tests for control system"""

    @pytest.fixture
    def constraint_config_schema(self):
        return ConstraintConfigSchema(
            **{
                "TECO_VFD": {
                    "default_constraints": {"RW_HZ": {"min": 0, "max": 60}},
                    "instances": {
                        "2": {"constraints": {"RW_HZ": {"min": 30, "max": 55}}},
                    },
                }
            }
        )

    @pytest.mark.asyncio
    async def test_when_incremental_policy_triggered_then_adjustment_applied(self, constraint_config_schema):
        """T1: Test incremental linear policy end-to-end"""
        config_yaml = """
        version: "1.0.0"
        SD400:
          default_controls: []
          instances:
            '3':
              use_default_controls: false
              controls:
                - name: Supply-Return Temperature Difference Control
                  code: LIN_INC01
                  priority: 10
                  composite:
                    any:
                      - type: difference
                        sources: [AIn01, AIn02]
                        operator: gt
                        threshold: 4.0
                  policy:
                    type: incremental_linear
                    condition_type: difference
                    sources: [AIn01, AIn02]
                    gain_hz_per_unit: 1.5
                  actions:
                    - model: TECO_VFD
                      slave_id: "2"
                      type: adjust_frequency
                      target: RW_HZ
        """

        # Arrange
        config_dict = yaml.safe_load(config_yaml)
        version = config_dict.pop("version", "1.0.0")
        control_config = ControlConfig(version=version, root=config_dict)

        # Mock
        mock_device = MagicMock()
        mock_device.model = "TECO_VFD"
        mock_device.slave_id = "2"

        mock_device.register_map = {"RW_HZ": {"writable": True}}

        mock_device.read_value = AsyncMock(return_value=50.0)
        mock_device.write_value = AsyncMock()

        mock_device_manager = MagicMock()
        mock_device_manager.get_device_by_model_and_slave_id.return_value = mock_device

        # Act
        evaluator = ControlEvaluator(control_config, constraint_config_schema)
        executor = ControlExecutor(mock_device_manager)

        snapshot = {"AIn01": 38.0, "AIn02": 25.0}
        model, slave_id = "SD400", "3"

        actions = evaluator.evaluate(model, slave_id, snapshot)

        # Assert
        assert len(actions) == 1

        action = actions[0]
        assert action.type == ControlActionType.ADJUST_FREQUENCY
        assert action.priority == 10
        assert action.value == 1.5

        await executor.execute(actions)

        mock_device_manager.get_device_by_model_and_slave_id.assert_called_once_with("TECO_VFD", "2")
        mock_device.read_value.assert_called_once_with("RW_HZ")

        expected_new_freq = 50.0 + 1.5
        mock_device.write_value.assert_called_once_with("RW_HZ", expected_new_freq)

    @pytest.mark.asyncio
    async def test_when_multiple_rules_triggered_then_all_executed(self, constraint_config_schema):
        """T2: Test cumulative execution - multiple rules"""
        config_yaml = """
        version: "1.0.0"
        SD400:
          default_controls: []
          instances:
            '3':
              use_default_controls: false
              controls:
                - name: Turn On VFD 1
                  code: TURN_ON_VFD1
                  priority: 10
                  composite:
                    any:
                      - type: threshold
                        sources:
                          - AIn01
                        operator: gt
                        threshold: 27.0
                  actions:
                    - model: TECO_VFD
                      slave_id: "1"
                      type: turn_on

                - name: Turn On VFD 2
                  code: TURN_ON_VFD2
                  priority: 20
                  composite:
                    any:
                      - type: threshold
                        sources:
                          - AIn01
                        operator: gt
                        threshold: 28.0
                  actions:
                    - model: TECO_VFD
                      slave_id: "2"
                      type: turn_on
        """

        # Arrange
        config_dict: dict = yaml.safe_load(config_yaml)
        version: str = config_dict.pop("version", "1.0.0")
        control_config = ControlConfig(version=version, root=config_dict)

        evaluator = ControlEvaluator(control_config, constraint_config_schema)

        # Temperature 29°C triggers both rules
        snapshot = {"AIn01": 29.0}
        model, slave_id = "SD400", "3"

        # Act
        actions = evaluator.evaluate(model, slave_id, snapshot)

        # Assert
        assert len(actions) == 2
        assert actions[0].slave_id == "1"
        assert actions[1].slave_id == "2"
        assert actions[0].priority == 10
        assert actions[1].priority == 20

    @pytest.mark.asyncio
    async def test_when_blocking_rule_triggered_then_stops_remaining_rules(self, constraint_config_schema):
        """T3: Test blocking mechanism"""
        config_yaml = """
        version: "1.0.0"
        SD400:
          default_controls: []
          instances:
            '3':
              use_default_controls: false
              controls:
                - name: Emergency Stop
                  code: EMERGENCY_STOP
                  priority: 0
                  blocking: true
                  composite:
                    any:
                      - type: threshold
                        sources:
                          - AIn01
                        operator: gt
                        threshold: 35.0
                  actions:
                    - model: TECO_VFD
                      slave_id: "1"
                      type: set_frequency
                      target: RW_HZ
                      value: 0

                - name: Normal Control
                  code: NORMAL_CONTROL
                  priority: 20
                  composite:
                    any:
                      - type: threshold
                        sources:
                          - AIn01
                        operator: gt
                        threshold: 25.0
                  actions:
                    - model: TECO_VFD
                      slave_id: "1"
                      type: set_frequency
                      target: RW_HZ
                      value: 50
        """

        # Arrange
        config_dict = yaml.safe_load(config_yaml)
        version = config_dict.pop("version", "1.0.0")
        control_config = ControlConfig(version=version, root=config_dict)

        # Act
        evaluator = ControlEvaluator(control_config, constraint_config_schema)

        # Temperature 36°C triggers both rules, but emergency blocks normal
        snapshot = {"AIn01": 36.0}
        model, slave_id = "SD400", "3"

        actions = evaluator.evaluate(model, slave_id, snapshot)

        # Assert
        assert len(actions) == 1
        assert actions[0].value == 0
        assert actions[0].priority == 0

    @pytest.mark.asyncio
    async def test_when_priority_conflict_then_higher_priority_protected(self, constraint_config_schema):
        """T4: Test priority protection mechanism"""
        config_yaml = """
        version: "1.0.0"
        SD400:
          default_controls: []
          instances:
            '3':
              use_default_controls: false
              controls:
                - name: High Priority Control
                  code: HIGH_PRIORITY
                  priority: 10
                  composite:
                    any:
                      - type: threshold
                        sources:
                          - AIn01
                        operator: gt
                        threshold: 25.0
                  actions:
                    - model: TECO_VFD
                      slave_id: "1"
                      type: set_frequency
                      target: RW_HZ
                      value: 50

                - name: Low Priority Control
                  code: LOW_PRIORITY
                  priority: 20
                  composite:
                    any:
                      - type: threshold
                        sources:
                          - AIn01
                        operator: gt
                        threshold: 28.0
                  actions:
                    - model: TECO_VFD
                      slave_id: "1"
                      type: set_frequency
                      target: RW_HZ
                      value: 55
        """

        # Arrange
        config_dict = yaml.safe_load(config_yaml)
        version = config_dict.pop("version", "1.0.0")
        control_config = ControlConfig(version=version, root=config_dict)

        # Mock
        mock_device = AsyncMock()
        mock_device.model = "TECO_VFD"
        mock_device.slave_id = "1"
        mock_device.register_map = {"RW_HZ": {"writable": True}}
        mock_device.read_value = AsyncMock(return_value=45.0)
        mock_device.write_value = AsyncMock()

        mock_device_manager = MagicMock()
        mock_device_manager.get_device_by_model_and_slave_id = MagicMock(return_value=mock_device)

        evaluator = ControlEvaluator(control_config, constraint_config_schema)
        executor = ControlExecutor(mock_device_manager)

        # Temperature 29°C triggers both rules
        snapshot = {"AIn01": 29.0}
        model, slave_id = "SD400", "3"

        # Act
        actions = evaluator.evaluate(model, slave_id, snapshot)

        # Assert
        assert len(actions) == 2
        assert actions[0].value == 50  # High priority
        assert actions[1].value == 55  # Low priority

        # Execute - high priority should be written, low priority should be protected
        await executor.execute(actions)

        # High priority writes 50
        assert mock_device.write_value.call_count == 1
        mock_device.write_value.assert_called_with("RW_HZ", 50)

    def test_when_no_conditions_triggered_then_returns_empty_actions(self, constraint_config_schema):
        """T5: Test scenario - No conditions triggered"""
        config_yaml = """
        version: "1.0.0"
        SD400:
          default_controls: []
          instances:
            '3':
              use_default_controls: false
              controls:
                - name: High Temperature Control
                  code: HIGH_TEMP
                  priority: 10
                  composite:
                    any:
                      - type: threshold
                        sources:
                          - AIn01
                        operator: gt
                        threshold: 40.0
                  actions:
                    - model: TECO_VFD
                      slave_id: "2"
                      type: set_frequency
                      target: RW_HZ
                      value: 60
        """

        # Arrange
        config_dict = yaml.safe_load(config_yaml)
        version = config_dict.pop("version", "1.0.0")
        control_config = ControlConfig(version=version, root=config_dict)

        evaluator = ControlEvaluator(control_config, constraint_config_schema)

        # Temperature too low
        snapshot = {"AIn01": 20.0}
        model, slave_id = "SD400", "3"

        # Act
        actions = evaluator.evaluate(model, slave_id, snapshot)

        # Assert
        assert len(actions) == 0
