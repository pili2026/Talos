"""
Evaluator Integration Tests — Mixed Actions Priority
- Verifies evaluator returns ALL matched actions, sorted by priority (smaller number = higher priority)
- Does NOT assert "only one action" — that is Executor's responsibility
"""

import pytest
import yaml

from core.evaluator.control_evaluator import ControlEvaluator
from core.schema.constraint_schema import ConstraintConfigSchema
from core.schema.control_condition_schema import ControlActionSchema, ControlActionType
from core.schema.control_config_schema import ControlConfig


@pytest.fixture
def constraint_cfg() -> ConstraintConfigSchema:
    """Basic constraints (present for completeness; evaluator doesn't enforce them)."""
    return ConstraintConfigSchema(
        **{
            "TECO_VFD": {
                "default_constraints": {"RW_HZ": {"min": 30, "max": 55}},
                "instances": {
                    "1": {"constraints": {"RW_HZ": {"min": 0, "max": 50}}},
                    "2": {"use_default_constraints": True},
                },
            }
        }
    )


@pytest.fixture
def mixed_config() -> ControlConfig:
    """Complete config with mixed action types and clear priorities."""
    yaml_text = """
version: "1.0.0"
SD400:
  default_controls: []
  instances:
    "3":
      use_default_controls: false
      controls:
        # p10 - Safety shutdown (highest)
        - name: "Low Temperature Turn Off Inverter"
          code: "LOW_TEMP_VFD_OFF"
          priority: 10
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

        # p11 - DO control (off)
        - name: "Low Temperature Turn Off DOut02"
          code: "LOW_TEMP_DO02_OFF"
          priority: 11
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
            - model: IMA_C
              slave_id: "5"
              type: write_do
              target: DOut02
              value: 0

        # p11 - Incremental frequency
        - name: "Supply-Return Temperature Difference Control"
          code: "LIN_INC01"
          priority: 11
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

        # p13 - DO control (on)
        - name: "High Temperature Turn On DOut01"
          code: "HIGH_TEMP_DO01_ON"
          priority: 13
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
            - model: IMA_C
              slave_id: "5"
              type: write_do
              target: DOut01
              value: 1

        # p13 - Absolute frequency
        - name: "Environment Temperature Linear Control"
          code: "LIN_ABS01"
          priority: 13
          composite:
            any:
              - type: threshold
                sources:
                  - AIn01
                operator: gt
                threshold: 25.0
          policy:
            type: absolute_linear
            condition_type: threshold
            sources:
              - AIn01
            base_freq: 40.0
            base_temp: 25.0
            gain_hz_per_unit: 1.2
          actions:
            - model: TECO_VFD
              slave_id: "2"
              type: set_frequency
              target: RW_HZ

        # p14 - Fixed frequency
        - name: "High Temperature Set Frequency"
          code: "HIGH_TEMP_FREQ"
          priority: 14
          composite:
            any:
              - type: threshold
                sources:
                  - AIn01
                operator: gt
                threshold: 40.0
              - type: threshold
                sources:
                  - AIn03
                operator: between
                min: 3.0
                max: 5.0
          policy:
            type: discrete_setpoint
          actions:
            - model: TECO_VFD
              slave_id: "2"
              type: set_frequency
              target: RW_HZ
              value: 45.0

        # p15 - Device turn on (lowest)
        - name: "High Temperature Turn On Inverter"
          code: "HIGH_TEMP_VFD_ON"
          priority: 15
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
"""
    data = yaml.safe_load(yaml_text)
    version = data.pop("version", "1.0.0")
    return ControlConfig(version=version, root=data)


@pytest.fixture
def evaluator(mixed_config: ControlConfig, constraint_cfg: ConstraintConfigSchema) -> ControlEvaluator:
    return ControlEvaluator(mixed_config, constraint_cfg)


def test_when_low_temperature_then_evaluator_returns_all_in_priority_order(evaluator: ControlEvaluator):
    """AIn01=20 (<25) triggers p10 and p11; ensure all returned and sorted: p10 first."""
    # Arrange
    snapshot = {"AIn01": 20.0, "AIn02": 18.0, "AIn03": 4.0}

    # Act
    action_list: list[ControlActionSchema] = evaluator.evaluate("SD400", "3", snapshot)

    # Assert
    assert len(action_list) >= 2
    priorities = [a.priority for a in action_list]
    assert priorities[0] == 10  # TURN_OFF first
    assert action_list[0].type == ControlActionType.TURN_OFF


def test_when_high_temperature_then_evaluator_accumulates_multiple_actions(evaluator: ControlEvaluator):
    """AIn01=45 (>40) triggers p13 (abs), p13 (DO on), p14 (fixed), p15 (turn on)."""
    # Arrange
    snapshot = {"AIn01": 45.0, "AIn02": 43.0, "AIn03": 4.0}

    # Act
    action_list: list[ControlActionSchema] = evaluator.evaluate("SD400", "3", snapshot)

    # Assert
    assert len(action_list) >= 3
    # Must be sorted: p13 before p14 before p15
    priorities = [a.priority for a in action_list]
    assert priorities == sorted(priorities)
    assert min(priorities) == 13
