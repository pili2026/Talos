import logging
from functools import partial

from evaluator.composite_evaluator import CompositeEvaluator
from model.control_model import ControlActionModel, ControlConditionModel
from model.enum.condition_enum import ConditionType, ControlActionType, ControlPolicyType
from model.policy_model import PolicyConfig
from schema.control_config_schema import ControlConfig

logger = logging.getLogger(__name__)


class ControlEvaluator:
    """Evaluates control conditions against snapshots and determines actions"""

    def __init__(self, control_config: ControlConfig):
        self.control_config = control_config
        self.composite_evaluator = CompositeEvaluator()

    def get_snapshot_value(self, snapshot: dict[str, float], key: str) -> float | None:
        """Fetch a numeric value by key from the given snapshot."""
        return snapshot.get(key)

    def evaluate(self, model: str, slave_id: str, snapshot: dict[str, float]) -> list[ControlActionModel]:
        """Evaluate control conditions and return the highest priority matching action"""
        conditions = self.control_config.get_control_list(model, slave_id)

        best_condition: ControlConditionModel | None = None
        best_priority: int | None = None

        get_value = partial(self.get_snapshot_value, snapshot)

        for condition_model in conditions:
            if condition_model.composite is None or condition_model.composite.invalid:
                continue

            is_matched: bool = self.composite_evaluator.evaluate_composite_node(condition_model.composite, get_value)
            if not is_matched:
                continue

            if best_condition is None:
                best_condition = condition_model
                best_priority = condition_model.priority
            else:
                if best_priority is None or condition_model.priority > best_priority:
                    best_condition = condition_model
                    best_priority = condition_model.priority

        if best_condition is None:
            return []

        selected: ControlConditionModel = best_condition
        action: ControlActionModel = selected.action

        if not action.model or not action.slave_id:
            logger.warning(
                f"[EVAL] Skip rule '{selected.code}' (p={selected.priority}) " f"due to missing action fields"
            )
            return []

        # Apply policy processing
        processed_action = self._apply_policy_to_action(selected, action, snapshot)
        if processed_action is None:
            logger.warning(
                f"[EVAL] Skip rule '{selected.code}' (p={selected.priority}) " f"due to policy processing failure"
            )
            return []

        # Build reason string
        try:
            comp_summary = (
                self.composite_evaluator.build_composite_reason_summary(selected.composite)
                if selected.composite
                else "composite"
            )
        except Exception:
            comp_summary = "composite"

        processed_action.reason = f"[{selected.code}] {selected.name} | {comp_summary} | priority={selected.priority}"

        logger.info(
            f"[EVAL] Pick '{selected.code}' (p={selected.priority}) " f"model={model} slave_id={slave_id} via composite"
        )
        return [processed_action]

    def _apply_policy_to_action(
        self, condition: ControlConditionModel, action: ControlActionModel, snapshot: dict[str, float]
    ) -> ControlActionModel | None:
        """Apply policy processing to calculate dynamic action values"""
        if condition.policy is None:
            return action

        policy: PolicyConfig = condition.policy

        if policy.type == ControlPolicyType.DISCRETE_SETPOINT:
            return action

        elif policy.type == ControlPolicyType.ABSOLUTE_LINEAR:
            # Single temperature value control
            if not policy.source:
                logger.warning(f"[EVAL] ABSOLUTE_LINEAR missing source")
                return None

            temp_value = snapshot.get(policy.source)
            if temp_value is None:
                logger.warning(f"[EVAL] Cannot get temperature value for {policy.source}")
                return None

            # Validate required fields
            if policy.base_temp is None:
                logger.warning(f"[EVAL] ABSOLUTE_LINEAR missing base_temp")
                return None

            # Calculate target frequency: base_freq + (temp - base_temp) * gain
            target_freq = policy.base_freq + (temp_value - policy.base_temp) * policy.gain_hz_per_unit

            new_action = action.model_copy()
            new_action.value = target_freq
            new_action.type = ControlActionType.SET_FREQUENCY  # Absolute setting
            logger.info(
                f"[EVAL] Absolute linear: temp={temp_value}°C, base_temp={policy.base_temp}°C, target_freq={target_freq}Hz"
            )
            return new_action

        elif policy.type == ControlPolicyType.INCREMENTAL_LINEAR:
            # Temperature difference control
            condition_value = self._get_condition_value(policy, snapshot)  # Calculate temperature difference
            if condition_value is None:
                logger.warning(f"[EVAL] Cannot get condition value for incremental_linear policy")
                return None

            # Calculate adjustment directly (max_step_hz limitation removed)
            adjustment: float = condition_value * policy.gain_hz_per_unit

            new_action = action.model_copy()
            new_action.type = ControlActionType.ADJUST_FREQUENCY  # Incremental adjustment
            new_action.value = adjustment
            logger.info(f"[EVAL] Incremental linear: temp_diff={condition_value}°C, adjustment={adjustment}Hz")
            return new_action

        else:
            logger.warning(f"[EVAL] Unsupported policy type: {policy.type}")
            return action

    def _get_condition_value(self, policy: PolicyConfig, snapshot: dict[str, float]) -> float | None:
        """Get condition value based on policy type"""
        if policy.condition_type == ConditionType.THRESHOLD:
            # Single sensor value
            if not policy.source:
                return None
            return snapshot.get(policy.source)

        elif policy.condition_type == ConditionType.DIFFERENCE:
            # Difference between two sensors
            if not policy.sources or len(policy.sources) != 2:
                return None
            v1, v2 = snapshot.get(policy.sources[0]), snapshot.get(policy.sources[1])
            if v1 is None or v2 is None:
                return None
            return v1 - v2

        else:
            logger.warning(f"[EVAL] Unknown condition_type: {policy.condition_type}")
            return None
