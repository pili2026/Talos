import logging
from functools import partial

from evaluator.composite_evaluator import CompositeEvaluator
from model.control_model import ControlActionModel, ControlConditionModel
from model.enum.condition_enum import ConditionType, ControlActionType, ControlPolicyType
from model.policy_model import PolicyConfig
from schema.constraint_schema import ConstraintConfigSchema, InstanceConfig
from schema.control_config_schema import ControlConfig

logger = logging.getLogger(__name__)


class ControlEvaluator:
    """Evaluates control conditions against snapshots and determines actions"""

    def __init__(self, control_config: ControlConfig, constraint_config_schema: ConstraintConfigSchema):
        self.control_config = control_config
        self.constraint_config_schema = constraint_config_schema
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

        if action.emergency_override:
            processed_action: ControlActionModel | None = self._handle_emergency_override(action)
        else:
            processed_action: ControlActionModel | None = self._apply_policy_to_action(
                condition=selected, action=action, snapshot=snapshot
            )

        if processed_action is None:
            logger.warning(
                f"[EVAL] Skip rule '{selected.code}' (p={selected.priority}) " f"due to policy processing failure"
            )
            return []

        # Build reason string
        try:
            composite_summary = (
                self.composite_evaluator.build_composite_reason_summary(selected.composite)
                if selected.composite
                else "composite"
            )
        except Exception:
            composite_summary = "composite"

        if action.emergency_override and processed_action.reason:
            # Emergency information is at the front (most important), with additional control details
            processed_action.reason = (
                f"{processed_action.reason} | "
                f"[{selected.code}] {selected.name} | {composite_summary} | priority={selected.priority}"
            )
        else:
            # Normal Situation
            processed_action.reason = (
                f"[{selected.code}] {selected.name} | {composite_summary} | priority={selected.priority}"
            )

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
            return self._apply_absolute_linear_policy(action=action, policy=policy, snapshot=snapshot)

        elif policy.type == ControlPolicyType.INCREMENTAL_LINEAR:
            return self._apply_incremental_linear_policy(action=action, policy=policy, snapshot=snapshot)

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

    def _apply_absolute_linear_policy(
        self, action: ControlActionModel, policy: PolicyConfig, snapshot: dict[str, float]
    ) -> ControlActionModel | None:
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

    def _apply_incremental_linear_policy(
        self, action: ControlActionModel, policy: PolicyConfig, snapshot: dict[str, float]
    ) -> ControlActionModel | None:
        # Temperature difference control
        condition_value = self._get_condition_value(policy, snapshot)  # Calculate temperature difference
        if condition_value is None:
            logger.warning(f"[EVAL] Cannot get condition value for incremental_linear policy")
            return None

        if condition_value > 0:
            adjustment = policy.gain_hz_per_unit  # +1.5Hz
        else:
            adjustment = -policy.gain_hz_per_unit

        new_action = action.model_copy()
        new_action.type = ControlActionType.ADJUST_FREQUENCY  # Incremental adjustment
        new_action.value = adjustment
        logger.info(f"[EVAL] Incremental linear: temp_diff={condition_value}°C, adjustment={adjustment}Hz")
        return new_action

    def _handle_emergency_override(self, action: ControlActionModel) -> ControlActionModel | None:
        """Handle emergency override logic: ensure the target can reach 60 Hz if needed.

        Rules:
        - If constraint max exists and is below 60 → override to 60.
        - If constraint max equals 60 → use 60.
        - If constraint max is unknown (None) → keep original value but note unknown in reason.
        """
        constraint_max = self._get_constraint_max(action.model, action.slave_id)

        new_action = action.model_copy()

        if constraint_max is not None and constraint_max < 60:
            # Bypass constraint and force 60 Hz
            new_action.value = 60
            new_action.reason = f"[EMERGENCY] Override constraint {constraint_max} → 60 Hz due to emergency condition"
            logger.critical(
                f"[EMERGENCY] {action.model}_{action.slave_id}: Override constraint {constraint_max} → 60 Hz"
            )
        elif constraint_max == 60:
            # Use the constraint ceiling directly
            new_action.value = constraint_max
            new_action.reason = f"[EMERGENCY] Use constraint max: {constraint_max} Hz due to emergency condition"
            logger.warning(f"[EMERGENCY] {action.model}_{action.slave_id}: Use constraint max: {constraint_max} Hz")
        else:
            # constraint_max is None or >= 60 → keep original value
            new_action.reason = f"[EMERGENCY] Use original value: {action.value} (constraint_max={constraint_max})"
            logger.warning(
                f"[EMERGENCY] {action.model}_{action.slave_id}: Use original value {action.value} "
                f"(constraint_max={constraint_max})"
            )

        return new_action

    def _get_constraint_max(self, model: str, slave_id: str) -> float | None:
        """Return the max RW_HZ constraint for the given device (instance → model default → None)."""
        if self.constraint_config_schema is None:
            logger.warning("[EMERGENCY] No constraint_config available for emergency override check")
            return None

        try:
            devices = self.constraint_config_schema.devices
            device_cfg = devices.get(model)
            if device_cfg is None:
                return None

            instances = device_cfg.instances or {}
            instances_config: InstanceConfig | None = instances.get(str(slave_id))

            if instances_config:
                inst_constraints = instances_config.constraints or {}
                rw_hz_cfg = inst_constraints.get("RW_HZ")
                if rw_hz_cfg and rw_hz_cfg.max is not None:
                    return float(rw_hz_cfg.max)

                use_defaults = instances_config.use_default_constraints
                if not use_defaults:
                    return None

            default_constraints = device_cfg.default_constraints or {}
            rw_hz_default = default_constraints.get("RW_HZ")
            if rw_hz_default and rw_hz_default.max is not None:
                return float(rw_hz_default.max)

            return None

        except Exception as e:
            logger.warning(f"[EMERGENCY] Failed to get RW_HZ max for {model}_{slave_id}: {e}")
            return None
