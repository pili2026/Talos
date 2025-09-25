import logging
from functools import partial

from evaluator.composite_evaluator import CompositeEvaluator
from model.control_model import ControlActionModel, ControlConditionModel
from model.enum.condition_enum import ConditionType, ControlActionType, ControlPolicyType
from model.policy_model import PolicyConfig
from schema.control_config_schema import ControlConfig

logger = logging.getLogger(__name__)


class ControlEvaluator:
    """
    Clean version without unnecessary getattr calls.
    Since we have proper Pydantic schemas, we can access attributes directly.
    """

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

        selected = best_condition
        action = selected.action

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

        policy = condition.policy

        if policy.type == ControlPolicyType.DISCRETE_SETPOINT:
            return action

        elif policy.type == ControlPolicyType.ABSOLUTE_LINEAR:
            condition_value = self._get_condition_value(policy, snapshot)
            if condition_value is None:
                logger.warning(f"[EVAL] Cannot get condition value for absolute_linear policy")
                return None

            adjusted_value = condition_value

            if policy.abs:
                adjusted_value = abs(adjusted_value)

            if abs(adjusted_value) <= policy.deadband:
                logger.info(f"[EVAL] Value {adjusted_value} within deadband {policy.deadband}, using base frequency")
                calculated_freq = policy.base_freq
            else:
                excess = abs(adjusted_value) - policy.deadband
                calculated_freq = policy.base_freq + excess * policy.gain_hz_per_unit

            new_action = action.model_copy()
            new_action.value = calculated_freq
            logger.info(
                f"[EVAL] Absolute linear: base={policy.base_freq}, condition={condition_value}, calculated={calculated_freq}"
            )
            return new_action

        elif policy.type == ControlPolicyType.INCREMENTAL_LINEAR:
            condition_value = self._get_condition_value(policy, snapshot)
            if condition_value is None:
                logger.warning(f"[EVAL] Cannot get condition value for incremental_linear policy")
                return None

            if abs(condition_value) <= policy.deadband:
                logger.info(f"[EVAL] Value {condition_value} within deadband {policy.deadband}, no adjustment")
                return None

            if condition_value > policy.deadband:
                excess = condition_value - policy.deadband
            elif condition_value < -policy.deadband:
                excess = condition_value + policy.deadband
            else:
                return None

            adjustment: float = excess * policy.gain_hz_per_unit

            if policy.max_step_hz is not None and abs(adjustment) > policy.max_step_hz:
                adjustment = policy.max_step_hz * (1 if adjustment > 0 else -1)

            new_action = action.model_copy()
            new_action.type = ControlActionType.ADJUST_FREQUENCY
            new_action.value = adjustment
            logger.info(f"[EVAL] Incremental linear: condition={condition_value}, adjustment={adjustment}")
            return new_action

        else:
            logger.warning(f"[EVAL] Unknown policy type: {policy.type}")
            return action

    def _get_condition_value(self, policy: PolicyConfig, snapshot: dict[str, float]) -> float | None:
        """Calculate condition value based on policy.condition_type"""

        if policy.condition_type == ConditionType.DIFFERENCE:
            if not policy.sources or len(policy.sources) != 2:
                logger.warning(f"[EVAL] Invalid sources for difference condition: {policy.sources}")
                return None
            v1 = snapshot.get(policy.sources[0])
            v2 = snapshot.get(policy.sources[1])
            if v1 is None or v2 is None:
                logger.warning(f"[EVAL] Missing values for sources {policy.sources}: v1={v1}, v2={v2}")
                return None
            return float(v1) - float(v2)

        logger.warning(f"[EVAL] Unknown condition_type: {policy.condition_type}")
        return None
