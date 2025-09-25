import logging
from functools import partial
from typing import Optional

from evaluator.composite_evaluator import CompositeEvaluator
from model.control_composite import CompositeNode
from model.control_model import ControlActionModel, ControlConditionModel
from schema.control_config_schema import ControlConfig

logger = logging.getLogger(__name__)


class ControlEvaluator:
    """
    Responsibilities:
    - Retrieve the control rule list for the specified (model, slave_id)
    - Evaluate each rule and select the one that matches with the highest priority
    - Apply policy processing to calculate dynamic values
    - Return the corresponding Action (at most one)
    """

    def __init__(self, control_config: ControlConfig):
        self.control_config = control_config
        self.composite_evaluator = CompositeEvaluator()

    # Centralized snapshot access (easy to refactor later)
    def get_snapshot_value(self, snapshot: dict[str, float], key: str) -> Optional[float]:
        """
        Fetch a numeric value by key from the given snapshot.
        If your snapshot structure changes (namespacing, nesting, etc.),
        just update this method.
        """
        return snapshot.get(key)

    def evaluate(self, model: str, slave_id: str, snapshot: dict[str, float]) -> list[ControlActionModel]:
        """
        Evaluate control conditions and return the highest priority matching action
        """
        condition_model_list: list[ControlConditionModel] = self.control_config.get_control_list(model, slave_id)

        best_condition: ControlConditionModel | None = None
        best_priority: int | None = None

        # Pre-bind snapshot so the callback fits Callable[[str], Optional[float]]
        get_value = partial(self.get_snapshot_value, snapshot)

        for condition_model in condition_model_list:
            composite: CompositeNode = getattr(condition_model, "composite", None)
            if composite is None or getattr(composite, "invalid", False):
                continue

            is_matched: bool = self.composite_evaluator.evaluate_composite_node(composite, get_value)
            if not is_matched:
                continue

            # Keep only the highest priority; if equal, keep the first encountered
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
        action: ControlActionModel = selected.action

        missing_field_list = []
        if not action.model:
            missing_field_list.append("model")
        if not action.slave_id:
            missing_field_list.append("slave_id")

        if missing_field_list:
            logger.warning(
                f"[EVAL] Skip rule '{selected.code}' (p={selected.priority}) "
                f"due to missing action fields: {', '.join(missing_field_list)}"
            )
            return []

        # Apply policy processing to calculate dynamic values
        processed_action = self._apply_policy_to_action(selected, action, snapshot)
        if processed_action is None:
            logger.warning(
                f"[EVAL] Skip rule '{selected.code}' (p={selected.priority}) " f"due to policy processing failure"
            )
            return []

        # Concise reason (composite summary)
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
    ) -> Optional[ControlActionModel]:
        """
        Apply policy processing to calculate dynamic action values

        Args:
            condition: The matched control condition with policy definition
            action: The base action from YAML configuration
            snapshot: Current sensor data snapshot

        Returns:
            Processed action with calculated values, or None if processing fails
        """
        if not hasattr(condition, "policy") or not condition.policy:
            # No policy defined, return original action (discrete_setpoint case)
            return action

        policy = condition.policy

        if policy.type == "discrete_setpoint":
            # Use fixed value from YAML configuration
            return action

        elif policy.type == "absolute_linear":
            # Calculate absolute frequency: base_freq + (condition_value - deadband) * gain
            condition_value = self._get_condition_value(policy, snapshot)
            if condition_value is None:
                logger.warning(f"[EVAL] Cannot get condition value for absolute_linear policy")
                return None

            adjusted_value = condition_value
            if getattr(policy, "abs", False):
                adjusted_value = abs(adjusted_value)

            # Apply deadband logic
            deadband = getattr(policy, "deadband", 0.0)
            if abs(adjusted_value) <= deadband:
                logger.info(f"[EVAL] Value {adjusted_value} within deadband {deadband}, using base frequency")
                calculated_freq = getattr(policy, "base_freq", 0.0)
            else:
                excess = abs(adjusted_value) - deadband
                base_freq = getattr(policy, "base_freq", 0.0)
                gain = getattr(policy, "gain_hz_per_unit", 1.0)
                calculated_freq = base_freq + excess * gain

            # Create new action with calculated value
            new_action = action.model_copy()
            new_action.value = calculated_freq
            logger.info(
                f"[EVAL] Absolute linear: base={getattr(policy, 'base_freq', 0.0)}, condition={condition_value}, calculated={calculated_freq}"
            )
            return new_action

        elif policy.type == "incremental_linear":
            # Calculate incremental adjustment
            condition_value = self._get_condition_value(policy, snapshot)
            if condition_value is None:
                logger.warning(f"[EVAL] Cannot get condition value for incremental_linear policy")
                return None

            deadband = getattr(policy, "deadband", 0.0)

            # Calculate excess beyond deadband
            if abs(condition_value) <= deadband:
                logger.info(f"[EVAL] Value {condition_value} within deadband {deadband}, no adjustment")
                return None  # No adjustment needed

            # Calculate adjustment direction and magnitude
            if condition_value > deadband:
                excess = condition_value - deadband
            elif condition_value < -deadband:
                excess = condition_value + deadband
            else:
                return None

            gain = getattr(policy, "gain_hz_per_unit", 1.0)
            adjustment = excess * gain

            # Apply maximum step limitation
            max_step = getattr(policy, "max_step_hz", None)
            if max_step is not None and abs(adjustment) > max_step:
                adjustment = max_step * (1 if adjustment > 0 else -1)

            # Create new action with ADJUST_FREQUENCY type
            new_action = action.model_copy()
            new_action.type = "adjust_frequency"  # Change to incremental adjustment
            new_action.value = adjustment
            logger.info(f"[EVAL] Incremental linear: condition={condition_value}, adjustment={adjustment}")
            return new_action

        else:
            logger.warning(f"[EVAL] Unknown policy type: {policy.type}")
            return action

    def _get_condition_value(self, policy, snapshot: dict[str, float]) -> Optional[float]:
        """
        Calculate condition value based on policy.condition_type

        Args:
            policy: Policy object with condition_type and sources
            snapshot: Current sensor data snapshot

        Returns:
            Calculated condition value, or None if calculation fails
        """
        condition_type = getattr(policy, "condition_type", None)

        if condition_type == "difference":
            sources = getattr(policy, "sources", None)
            if not sources or len(sources) != 2:
                return None
            v1 = snapshot.get(sources[0])
            v2 = snapshot.get(sources[1])
            if v1 is None or v2 is None:
                return None
            return float(v1) - float(v2)

        # Future: Add support for other condition types
        # elif condition_type == "threshold":
        #     source = getattr(policy, 'source', None)
        #     return snapshot.get(source) if source else None

        return None
