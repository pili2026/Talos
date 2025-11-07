"""
Control System Tests (clean version for current design)
- Evaluator: cumulative results + sorted by priority (smaller number → higher priority)
- Executor: for the same device+target, higher-priority action wins; different targets both execute
- Integration: verify emergency (blocking vs non-blocking) and policy calculations
"""

import pytest
import yaml
from unittest.mock import Mock, AsyncMock

from evaluator.control_evaluator import ControlEvaluator
from executor.control_executor import ControlExecutor
from schema.control_config_schema import ControlConfig
from schema.constraint_schema import ConstraintConfigSchema
from schema.control_condition_schema import ControlActionSchema
from model.device_constant import REG_RW_ON_OFF
from model.enum.condition_enum import ControlActionType

# ---------------------------
# Constants (avoid magic strings)
# ---------------------------

MODEL_SD400 = "SD400"
MODEL_VFD = "TECO_VFD"
SLAVE_ID_1 = "1"
SLAVE_ID_2 = "2"
INSTANCE_ID = "3"

TARGET_HZ = "RW_HZ"
TARGET_ON_OFF = "RW_ON_OFF"
TARGET_DO = "RW_DO"


# ---------------------------
# Fixtures
# ---------------------------


@pytest.fixture
def mock_device() -> Mock:
    """Simulate a device supporting HZ and ON/OFF/DO (with proper AsyncMock setup)."""
    device = Mock()
    device.model = MODEL_VFD
    device.slave_id = SLAVE_ID_2
    device.register_map = {
        TARGET_HZ: {"writable": True, "address": 8193},
        TARGET_ON_OFF: {"writable": True, "address": 8192},
        TARGET_DO: {"writable": True, "address": 8200},
    }
    device.read_value = AsyncMock(return_value=50.0)
    device.write_value = AsyncMock()
    device.write_on_off = AsyncMock()
    device.supports_on_off = Mock(return_value=True)
    return device


@pytest.fixture
def mock_device_manager(mock_device: Mock) -> Mock:
    """Mock AsyncDeviceManager boundary."""
    manager = Mock()
    manager.get_device_by_model_and_slave_id = Mock(return_value=mock_device)
    return manager


@pytest.fixture
def constraint_config_schema() -> ConstraintConfigSchema:
    """Provide basic frequency min/max limits (used for emergency tests if needed)."""
    return ConstraintConfigSchema(
        **{
            MODEL_VFD: {
                "default_constraints": {TARGET_HZ: {"min": 30, "max": 55}},
                "instances": {
                    SLAVE_ID_1: {"constraints": {TARGET_HZ: {"min": 0, "max": 50}}},
                    SLAVE_ID_2: {"use_default_constraints": True},
                },
            }
        }
    )


# =========================================================
# ① Evaluator: cumulative & ordering
# =========================================================


class TestEvaluatorCumulativeAndOrder:
    @pytest.fixture
    def control_config(self) -> ControlConfig:
        yaml_text = """
version: "1.0.0"
SD400:
  default_controls: []
  instances:
    "3":
      use_default_controls: false
      controls:
        - name: "High Temperature Fixed Setpoint"
          code: "DISCRETE"
          priority: 10
          composite:
            any:
              - type: threshold
                sources:
                  - AIn01
                operator: gt
                threshold: 25.0
          policy:
            type: discrete_setpoint
          actions:
            - model: TECO_VFD
              slave_id: "2"
              type: set_frequency
              target: RW_HZ
              value: 45

        - name: "Absolute Linear Control"
          code: "ABS"
          priority: 11
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

        - name: "Incremental Linear Control"
          code: "INC"
          priority: 12
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
        config_dict = yaml.safe_load(yaml_text)
        version = config_dict.pop("version", "1.0.0")
        return ControlConfig(version=version, root=config_dict)

    @pytest.fixture
    def evaluator(
        self, control_config: ControlConfig, constraint_config_schema: ConstraintConfigSchema
    ) -> ControlEvaluator:
        return ControlEvaluator(control_config, constraint_config_schema)

    def test_when_all_three_rules_match_then_actions_are_sorted_by_priority(self, evaluator: ControlEvaluator) -> None:
        """
        Expectation:
        - All three rules match → return 3 actions
        - Sorted by priority: 10(DISC) → 11(ABS) → 12(INC)
        - ABS value = 40 + (AIn01 - 25) * 1.2
        - INC value = +1.5 (positive difference)
        """
        # Arrange
        snapshot = {"AIn01": 35.0, "AIn02": 25.0}  # diff=10

        # Act
        actions = evaluator.evaluate(MODEL_SD400, INSTANCE_ID, snapshot)

        # Assert
        assert len(actions) == 3

        priorities = [a.priority for a in actions]
        assert priorities == [10, 11, 12]

        abs_action = actions[1]
        assert abs_action.type == ControlActionType.SET_FREQUENCY
        assert abs_action.target == TARGET_HZ
        assert abs_action.value == pytest.approx(40.0 + (35.0 - 25.0) * 1.2, abs=1e-6)

        inc_action = actions[2]
        assert inc_action.type == ControlActionType.ADJUST_FREQUENCY
        assert inc_action.target == TARGET_HZ
        assert inc_action.value == pytest.approx(1.5, abs=1e-6)


# =========================================================
# ② Executor: same-target protection & different-target parallelism
# =========================================================


class TestExecutorPriorityProtectionAndParallelTargets:
    @pytest.fixture
    def executor(self, mock_device_manager: Mock) -> ControlExecutor:
        return ControlExecutor(mock_device_manager)

    @pytest.mark.asyncio
    async def test_when_two_actions_target_same_then_higher_priority_value_wins(
        self, executor: ControlExecutor
    ) -> None:
        """
        Same device+target (RW_HZ), priority 10 vs 20:
        - Only one write, using priority=10 value (48.0)
        """
        # Arrange
        high_priority_action = ControlActionSchema(
            model=MODEL_VFD,
            slave_id=SLAVE_ID_2,
            type=ControlActionType.SET_FREQUENCY,
            target=TARGET_HZ,
            value=48.0,
            priority=10,
            reason="[DISCRETE] High",
        )

        low_priority_action = ControlActionSchema(
            model=MODEL_VFD,
            slave_id=SLAVE_ID_2,
            type=ControlActionType.SET_FREQUENCY,
            target=TARGET_HZ,
            value=52.0,
            priority=20,
            reason="[ABS] Low",
        )

        # Act
        await executor.execute([high_priority_action, low_priority_action])

        device = executor.device_manager.get_device_by_model_and_slave_id(MODEL_VFD, SLAVE_ID_2)

        # Assert
        device.write_value.assert_called_once_with(TARGET_HZ, 48.0)

    @pytest.mark.asyncio
    async def test_when_targets_differ_then_both_actions_execute(self, executor: ControlExecutor) -> None:
        """
        Different targets (RW_HZ vs RW_DO) → both actions are executed.
        """
        # Arrange
        hz_action = ControlActionSchema(
            model=MODEL_VFD,
            slave_id=SLAVE_ID_2,
            type=ControlActionType.SET_FREQUENCY,
            target=TARGET_HZ,
            value=46.0,
            priority=10,
            reason="[DISC]",
        )

        do_action = ControlActionSchema(
            model=MODEL_VFD,
            slave_id=SLAVE_ID_2,
            type=ControlActionType.WRITE_DO,
            target=TARGET_DO,
            value=1,
            priority=20,
            reason="[DO]",
        )

        # Act
        await executor.execute([hz_action, do_action])

        device = executor.device_manager.get_device_by_model_and_slave_id(MODEL_VFD, SLAVE_ID_2)

        # Assert
        device.write_value.assert_any_call(TARGET_HZ, 46.0)
        device.write_value.assert_any_call(TARGET_DO, 1)
        assert device.write_value.call_count == 2

    @pytest.mark.asyncio
    async def test_when_turn_on_with_explicit_target_then_write_on_off_is_called_once(
        self, executor: ControlExecutor
    ) -> None:
        """
        Strict mode in tests: explicit target = RW_ON_OFF for TURN_ON/OFF.
        """
        # Arrange
        turn_on_action = ControlActionSchema(
            model=MODEL_VFD,
            slave_id=SLAVE_ID_2,
            type=ControlActionType.TURN_ON,
            target=REG_RW_ON_OFF,
            value=1,
            priority=10,
            reason="[ON]",
        )

        # Act
        await executor.execute([turn_on_action])

        device = executor.device_manager.get_device_by_model_and_slave_id(MODEL_VFD, SLAVE_ID_2)
        # Assert
        device.write_on_off.assert_called_once_with(1)


# =========================================================
# ③ Integration: Emergency (blocking vs non-blocking)
# =========================================================


class TestIntegrationEmergencyAndPolicy:
    @pytest.fixture
    def control_config_emergency_nonblocking(self) -> ControlConfig:
        """
        Normal and Emergency both match; no blocking:
        - Evaluator: returns both (Emergency must have higher priority and appear first)
        - Executor: same target → Emergency final result takes effect
        """
        yaml_text = """
version: "1.0.0"
SD400:
  default_controls: []
  instances:
    "3":
      use_default_controls: false
      controls:
        - name: "Normal"
          code: "NORMAL"
          priority: 10
          composite:
            any:
              - type: threshold
                sources:
                  - AIn01
                operator: gt
                threshold: 30.0
          policy:
            type: discrete_setpoint
          actions:
            - model: TECO_VFD
              slave_id: "1"
              type: set_frequency
              target: RW_HZ
              value: 45

        - name: "Emergency"
          code: "EMG"
          priority: 0
          composite:
            any:
              - type: threshold
                sources:
                  - AIn01
                operator: gt
                threshold: 32.0
          policy:
            type: discrete_setpoint
          actions:
            - model: TECO_VFD
              slave_id: "1"
              type: set_frequency
              target: RW_HZ
              value: 60
              emergency_override: true
"""
        config_dict = yaml.safe_load(yaml_text)
        version = config_dict.pop("version", "1.0.0")
        return ControlConfig(version=version, root=config_dict)

    @pytest.fixture
    def control_config_emergency_blocking(self) -> ControlConfig:
        """
        Emergency + blocking=true:
        - Evaluator: returns only Emergency
        """
        yaml_text = """
version: "1.0.0"
SD400:
  default_controls: []
  instances:
    "3":
      use_default_controls: false
      controls:
        - name: "Normal"
          code: "NORMAL"
          priority: 10
          composite:
            any:
              - type: threshold
                sources:
                  - AIn01
                operator: gt
                threshold: 30.0
          policy:
            type: discrete_setpoint
          actions:
            - model: TECO_VFD
              slave_id: "1"
              type: set_frequency
              target: RW_HZ
              value: 45

        - name: "Emergency"
          code: "EMG"
          priority: 0
          blocking: true
          composite:
            any:
              - type: threshold
                sources:
                  - AIn01
                operator: gt
                threshold: 32.0
          policy:
            type: discrete_setpoint
          actions:
            - model: TECO_VFD
              slave_id: "1"
              type: set_frequency
              target: RW_HZ
              value: 60
              emergency_override: true
"""
        config_dict = yaml.safe_load(yaml_text)
        version = config_dict.pop("version", "1.0.0")
        return ControlConfig(version=version, root=config_dict)

    @pytest.fixture
    def evaluator_nonblocking(
        self, control_config_emergency_nonblocking: ControlConfig, constraint_config_schema: ConstraintConfigSchema
    ) -> ControlEvaluator:
        return ControlEvaluator(control_config_emergency_nonblocking, constraint_config_schema)

    @pytest.fixture
    def evaluator_blocking(
        self, control_config_emergency_blocking: ControlConfig, constraint_config_schema: ConstraintConfigSchema
    ) -> ControlEvaluator:
        return ControlEvaluator(control_config_emergency_blocking, constraint_config_schema)

    @pytest.fixture
    def executor(self, mock_device_manager: Mock) -> ControlExecutor:
        return ControlExecutor(mock_device_manager)

    @pytest.mark.asyncio
    async def test_when_normal_and_emergency_trigger_nonblocking_then_executor_applies_emergency(
        self, evaluator_nonblocking: ControlEvaluator, executor: ControlExecutor, mock_device_manager: Mock
    ) -> None:
        """
        Evaluator: two actions (Emergency first).
        Executor: same target → final write uses Emergency (60).
        """
        # Arrange
        snapshot = {"AIn01": 35.0}

        # Act
        actions = evaluator_nonblocking.evaluate(MODEL_SD400, INSTANCE_ID, snapshot)

        # Assert
        # Evaluator: cumulative, Emergency priority=0 first
        assert len(actions) == 2
        assert actions[0].priority == 0
        assert actions[0].emergency_override is True

        # Mock
        # Executor: same RW_HZ target, write once with Emergency's value
        device = mock_device_manager.get_device_by_model_and_slave_id(MODEL_VFD, SLAVE_ID_1)
        device.read_value = AsyncMock(return_value=45.0)  # ensure "not equal" branch
        device.write_value = AsyncMock()

        # Act
        await executor.execute(actions)

        # Assert
        device.write_value.assert_called_once_with(TARGET_HZ, 60)

    def test_when_emergency_is_blocking_then_only_emergency_action_is_returned(
        self, evaluator_blocking: ControlEvaluator
    ) -> None:
        """blocking=true → Evaluator returns only Emergency."""
        # Arrange
        snapshot = {"AIn01": 35.0}

        # Act
        actions = evaluator_blocking.evaluate(MODEL_SD400, INSTANCE_ID, snapshot)

        # Assert
        assert len(actions) == 1
        assert actions[0].priority == 0
        assert actions[0].emergency_override is True
