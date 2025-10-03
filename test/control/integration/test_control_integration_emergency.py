"""
Emergency Control Integration Tests
Tests complete emergency override flow: Config → Evaluator → Executor → Device
"""

import pytest
from unittest.mock import Mock, AsyncMock
import yaml

from evaluator.control_evaluator import ControlEvaluator
from executor.control_executor import ControlExecutor
from schema.constraint_schema import ConstraintConfigSchema
from schema.control_config_schema import ControlConfig


class TestEmergencyControlIntegration:
    """Integration tests for emergency temperature control"""

    @pytest.fixture
    def constraint_config_with_limit_50(self):
        """Constraint config with max 50 Hz"""
        return ConstraintConfigSchema(
            **{"TECO_VFD": {"instances": {"1": {"constraints": {"RW_HZ": {"min": 0, "max": 50}}}}}}
        )

    @pytest.fixture
    def constraint_config_with_limit_60(self):
        """Constraint config with max 60 Hz"""
        return ConstraintConfigSchema(
            **{"TECO_VFD": {"instances": {"1": {"constraints": {"RW_HZ": {"min": 0, "max": 60}}}}}}
        )

    @pytest.fixture
    def constraint_config_no_limit(self):
        """Constraint config without RW_HZ limit"""
        return ConstraintConfigSchema(**{})

    # ================================
    # 1. Constraint Override Tests
    # ================================

    @pytest.mark.asyncio
    async def test_when_emergency_temperature_and_constraint_below_60_then_override_to_60(
        self, constraint_config_with_limit_50
    ):
        """Test 1: Emergency overrides constraint max when < 60"""
        config_yaml = """
version: "1.0.0"
SD400:
  default_controls: []
  instances:
    '3':
      use_default_controls: false
      controls:
        - name: Emergency High Water Temperature Override VFD1
          code: EMERGENCY_HIGH_WATER_TEMP_VFD1
          priority: 151
          composite:
            any:
              - type: threshold
                source: AIn01
                operator: gt
                threshold: 32.0
          policy:
            type: discrete_setpoint
          action:
            model: TECO_VFD
            slave_id: '1'
            type: set_frequency
            target: RW_HZ
            value: 60
            emergency_override: true
"""

        config_dict = yaml.safe_load(config_yaml)
        version = config_dict.pop("version", "1.0.0")
        control_config = ControlConfig(version=version, root=config_dict)

        evaluator = ControlEvaluator(control_config, constraint_config_with_limit_50)

        mock_device = Mock()
        mock_device.register_map = {"RW_HZ": {"writable": True}}
        mock_device.read_value = AsyncMock(return_value=45.0)
        mock_device.write_value = AsyncMock()

        mock_device_manager = Mock()
        mock_device_manager.get_device_by_model_and_slave_id = Mock(return_value=mock_device)

        executor = ControlExecutor(mock_device_manager)

        snapshot = {"AIn01": 35.0}

        # Act: Evaluate
        actions = evaluator.evaluate("SD400", "3", snapshot)

        # Assert: Emergency action with override
        assert len(actions) == 1
        action = actions[0]
        assert action.emergency_override is True
        assert action.value == 60
        assert "[EMERGENCY] Override constraint 50" in action.reason

        # Act: Execute
        await executor.execute(actions)

        # Assert: Device written with 60 Hz (not 50 Hz)
        mock_device.write_value.assert_called_once_with("RW_HZ", 60)

    @pytest.mark.asyncio
    async def test_when_emergency_and_constraint_equals_60_then_use_60(self, constraint_config_with_limit_60):
        """Test 2: Emergency uses constraint max when = 60"""
        config_yaml = """
version: "1.0.0"
SD400:
  default_controls: []
  instances:
    '3':
      use_default_controls: false
      controls:
        - name: Emergency High Water Temperature Override VFD1
          code: EMERGENCY_HIGH_WATER_TEMP_VFD1
          priority: 151
          composite:
            any:
              - type: threshold
                source: AIn01
                operator: gt
                threshold: 32.0
          policy:
            type: discrete_setpoint
          action:
            model: TECO_VFD
            slave_id: '1'
            type: set_frequency
            target: RW_HZ
            value: 60
            emergency_override: true
"""

        config_dict = yaml.safe_load(config_yaml)
        version = config_dict.pop("version", "1.0.0")
        control_config = ControlConfig(version=version, root=config_dict)

        evaluator = ControlEvaluator(control_config, constraint_config_with_limit_60)

        mock_device = Mock()
        mock_device.register_map = {"RW_HZ": {"writable": True}}
        mock_device.read_value = AsyncMock(return_value=45.0)
        mock_device.write_value = AsyncMock()

        mock_device_manager = Mock()
        mock_device_manager.get_device_by_model_and_slave_id = Mock(return_value=mock_device)

        executor = ControlExecutor(mock_device_manager)

        snapshot = {"AIn01": 35.0}

        # Act
        actions = evaluator.evaluate("SD400", "3", snapshot)

        # Assert
        assert len(actions) == 1
        action = actions[0]
        assert action.emergency_override is True
        assert action.value == 60
        assert "[EMERGENCY] Use constraint max: 60" in action.reason

        # Execute
        await executor.execute(actions)
        mock_device.write_value.assert_called_once_with("RW_HZ", 60)

    @pytest.mark.asyncio
    async def test_when_emergency_and_no_constraint_then_use_original_value(self, constraint_config_no_limit):
        """Test 3: Emergency uses original value when no constraint"""
        config_yaml = """
version: "1.0.0"
SD400:
  default_controls: []
  instances:
    '3':
      use_default_controls: false
      controls:
        - name: Emergency High Water Temperature Override VFD1
          code: EMERGENCY_HIGH_WATER_TEMP_VFD1
          priority: 151
          composite:
            any:
              - type: threshold
                source: AIn01
                operator: gt
                threshold: 32.0
          policy:
            type: discrete_setpoint
          action:
            model: TECO_VFD
            slave_id: '1'
            type: set_frequency
            target: RW_HZ
            value: 60
            emergency_override: true
"""

        config_dict = yaml.safe_load(config_yaml)
        version = config_dict.pop("version", "1.0.0")
        control_config = ControlConfig(version=version, root=config_dict)

        evaluator = ControlEvaluator(control_config, constraint_config_no_limit)

        snapshot = {"AIn01": 35.0}

        # Act
        actions = evaluator.evaluate("SD400", "3", snapshot)

        # Assert
        assert len(actions) == 1
        action = actions[0]
        assert action.value == 60
        assert "original value" in action.reason.lower()

    # ================================
    # 2. Trigger Condition Tests
    # ================================

    def test_when_normal_temperature_then_no_emergency_action(self, constraint_config_with_limit_50):
        """Test 4: Normal temperature does not trigger emergency"""
        config_yaml = """
version: "1.0.0"
SD400:
  default_controls: []
  instances:
    '3':
      use_default_controls: false
      controls:
        - name: Emergency High Water Temperature Override VFD1
          code: EMERGENCY_HIGH_WATER_TEMP_VFD1
          priority: 151
          composite:
            any:
              - type: threshold
                source: AIn01
                operator: gt
                threshold: 32.0
          policy:
            type: discrete_setpoint
          action:
            model: TECO_VFD
            slave_id: '1'
            type: set_frequency
            target: RW_HZ
            value: 60
            emergency_override: true
"""

        config_dict = yaml.safe_load(config_yaml)
        version = config_dict.pop("version", "1.0.0")
        control_config = ControlConfig(version=version, root=config_dict)

        evaluator = ControlEvaluator(control_config, constraint_config_with_limit_50)

        # Normal temperature: 30°C < 32°C threshold
        snapshot = {"AIn01": 30.0}

        # Act
        actions = evaluator.evaluate("SD400", "3", snapshot)

        # Assert: No actions generated
        assert len(actions) == 0

    def test_when_exactly_at_threshold_then_no_trigger(self, constraint_config_with_limit_50):
        """Test 5: Temperature exactly at threshold does not trigger (gt, not gte)"""
        config_yaml = """
version: "1.0.0"
SD400:
  default_controls: []
  instances:
    '3':
      use_default_controls: false
      controls:
        - name: Emergency High Water Temperature Override VFD1
          code: EMERGENCY_HIGH_WATER_TEMP_VFD1
          priority: 151
          composite:
            any:
              - type: threshold
                source: AIn01
                operator: gt
                threshold: 32.0
          policy:
            type: discrete_setpoint
          action:
            model: TECO_VFD
            slave_id: '1'
            type: set_frequency
            target: RW_HZ
            value: 60
            emergency_override: true
"""

        config_dict = yaml.safe_load(config_yaml)
        version = config_dict.pop("version", "1.0.0")
        control_config = ControlConfig(version=version, root=config_dict)

        evaluator = ControlEvaluator(control_config, constraint_config_with_limit_50)

        # Exactly at threshold: 32.0 == 32.0 (not > 32.0)
        snapshot = {"AIn01": 32.0}

        # Act
        actions = evaluator.evaluate("SD400", "3", snapshot)

        # Assert: Should not trigger (operator is gt, not gte)
        assert len(actions) == 0

    # ================================
    # 3. Priority Tests
    # ================================

    def test_when_multiple_emergency_controls_then_highest_priority_wins(self, constraint_config_with_limit_50):
        """Test 6: Highest priority emergency control wins"""
        config_yaml = """
version: "1.0.0"
SD400:
  default_controls: []
  instances:
    '3':
      use_default_controls: false
      controls:
        - name: Emergency VFD1 Priority 150
          code: EMERGENCY_VFD1_P150
          priority: 150
          composite:
            any:
              - type: threshold
                source: AIn01
                operator: gt
                threshold: 32.0
          policy:
            type: discrete_setpoint
          action:
            model: TECO_VFD
            slave_id: '1'
            type: set_frequency
            target: RW_HZ
            value: 55
            emergency_override: true
            
        - name: Emergency VFD1 Priority 151
          code: EMERGENCY_VFD1_P151
          priority: 151
          composite:
            any:
              - type: threshold
                source: AIn01
                operator: gt
                threshold: 32.0
          policy:
            type: discrete_setpoint
          action:
            model: TECO_VFD
            slave_id: '1'
            type: set_frequency
            target: RW_HZ
            value: 60
            emergency_override: true
"""

        config_dict = yaml.safe_load(config_yaml)
        version = config_dict.pop("version", "1.0.0")
        control_config = ControlConfig(version=version, root=config_dict)

        evaluator = ControlEvaluator(control_config, constraint_config_with_limit_50)

        snapshot = {"AIn01": 35.0}

        # Act
        actions = evaluator.evaluate("SD400", "3", snapshot)

        # Assert: Should select priority 151
        assert len(actions) == 1
        action = actions[0]
        assert "EMERGENCY_VFD1_P151" in action.reason
        assert "priority=151" in action.reason
        assert action.value == 60

    def test_when_emergency_and_normal_control_both_triggered_then_emergency_wins(
        self, constraint_config_with_limit_50
    ):
        """Test 7: Emergency control overrides normal control"""
        config_yaml = """
version: "1.0.0"
SD400:
  default_controls: []
  instances:
    '3':
      use_default_controls: false
      controls:
        - name: Normal High Temperature Control
          code: NORMAL_HIGH_TEMP
          priority: 90
          composite:
            any:
              - type: threshold
                source: AIn01
                operator: gt
                threshold: 30.0
          policy:
            type: discrete_setpoint
          action:
            model: TECO_VFD
            slave_id: '1'
            type: set_frequency
            target: RW_HZ
            value: 45
            
        - name: Emergency High Water Temperature Override
          code: EMERGENCY_HIGH_WATER_TEMP
          priority: 151
          composite:
            any:
              - type: threshold
                source: AIn01
                operator: gt
                threshold: 32.0
          policy:
            type: discrete_setpoint
          action:
            model: TECO_VFD
            slave_id: '1'
            type: set_frequency
            target: RW_HZ
            value: 60
            emergency_override: true
"""

        config_dict = yaml.safe_load(config_yaml)
        version = config_dict.pop("version", "1.0.0")
        control_config = ControlConfig(version=version, root=config_dict)

        evaluator = ControlEvaluator(control_config, constraint_config_with_limit_50)

        # Both conditions triggered: 35°C > 30°C and 35°C > 32°C
        snapshot = {"AIn01": 35.0}

        # Act
        actions = evaluator.evaluate("SD400", "3", snapshot)

        # Assert: Should select emergency (priority 151 > 90)
        assert len(actions) == 1
        action = actions[0]
        assert action.emergency_override is True
        assert "EMERGENCY_HIGH_WATER_TEMP" in action.reason
        assert action.value == 60

    # ================================
    # 4. Multiple Device Tests
    # ================================

    @pytest.mark.asyncio
    async def test_when_two_emergency_controls_for_different_devices(self):
        """Test 8: Multiple emergency controls for different devices"""
        config_yaml = """
version: "1.0.0"
SD400:
  default_controls: []
  instances:
    '3':
      use_default_controls: false
      controls:
        - name: Emergency VFD1
          code: EMERGENCY_VFD1
          priority: 151
          composite:
            any:
              - type: threshold
                source: AIn01
                operator: gt
                threshold: 32.0
          policy:
            type: discrete_setpoint
          action:
            model: TECO_VFD
            slave_id: '1'
            type: set_frequency
            target: RW_HZ
            value: 60
            emergency_override: true
            
        - name: Emergency VFD2
          code: EMERGENCY_VFD2
          priority: 150
          composite:
            any:
              - type: threshold
                source: AIn02
                operator: gt
                threshold: 34.0
          policy:
            type: discrete_setpoint
          action:
            model: TECO_VFD
            slave_id: '2'
            type: set_frequency
            target: RW_HZ
            value: 60
            emergency_override: true
"""

        constraint_config = ConstraintConfigSchema(
            **{
                "TECO_VFD": {
                    "instances": {
                        "1": {"constraints": {"RW_HZ": {"min": 0, "max": 50}}},
                        "2": {"constraints": {"RW_HZ": {"min": 0, "max": 55}}},
                    }
                }
            }
        )

        config_dict = yaml.safe_load(config_yaml)
        version = config_dict.pop("version", "1.0.0")
        control_config = ControlConfig(version=version, root=config_dict)

        evaluator = ControlEvaluator(control_config, constraint_config)

        # Only VFD1 triggers: AIn01 > 32.0, AIn02 < 34.0
        snapshot = {"AIn01": 35.0, "AIn02": 33.0}

        # Act
        actions = evaluator.evaluate("SD400", "3", snapshot)

        # Assert: Should select VFD1 (higher priority 151)
        assert len(actions) == 1
        action = actions[0]
        assert action.slave_id == "1"
        assert "Override constraint 50" in action.reason

    # ================================
    # 5. Complete Flow Test
    # ================================

    @pytest.mark.asyncio
    async def test_complete_emergency_flow_end_to_end(self, constraint_config_with_limit_50):
        """Test 9: Complete emergency flow from evaluation to device write"""
        config_yaml = """
version: "1.0.0"
SD400:
  default_controls: []
  instances:
    '3':
      use_default_controls: false
      controls:
        - name: Emergency High Water Temperature Override VFD1
          code: EMERGENCY_HIGH_WATER_TEMP_VFD1
          priority: 151
          composite:
            any:
              - type: threshold
                source: AIn01
                operator: gt
                threshold: 32.0
          policy:
            type: discrete_setpoint
          action:
            model: TECO_VFD
            slave_id: '1'
            type: set_frequency
            target: RW_HZ
            value: 60
            emergency_override: true
"""

        config_dict = yaml.safe_load(config_yaml)
        version = config_dict.pop("version", "1.0.0")
        control_config = ControlConfig(version=version, root=config_dict)

        evaluator = ControlEvaluator(control_config, constraint_config_with_limit_50)

        # Setup mock device
        mock_device = Mock()
        mock_device.model = "TECO_VFD"
        mock_device.slave_id = "1"
        mock_device.register_map = {"RW_HZ": {"writable": True}}
        mock_device.read_value = AsyncMock(return_value=40.0)  # Current: 40 Hz
        mock_device.write_value = AsyncMock()

        mock_device_manager = Mock()
        mock_device_manager.get_device_by_model_and_slave_id = Mock(return_value=mock_device)

        executor = ControlExecutor(mock_device_manager)

        # Emergency temperature
        snapshot = {"AIn01": 35.0}

        # Act: Step 1 - Evaluate
        actions = evaluator.evaluate("SD400", "3", snapshot)

        # Assert: Evaluation results
        assert len(actions) == 1
        action = actions[0]
        assert action.emergency_override is True
        assert action.model == "TECO_VFD"
        assert action.slave_id == "1"
        assert action.type.value == "set_frequency"
        assert action.target == "RW_HZ"
        assert action.value == 60
        assert "[EMERGENCY] Override constraint 50" in action.reason
        assert "priority=151" in action.reason

        # Act: Step 2 - Execute
        await executor.execute(actions)

        # Assert: Execution calls
        mock_device_manager.get_device_by_model_and_slave_id.assert_called_once_with("TECO_VFD", "1")
        mock_device.read_value.assert_called_once_with("RW_HZ")
        mock_device.write_value.assert_called_once_with("RW_HZ", 60)
