import logging
from functools import partial

from typing import Callable

from evaluator.composite_evaluator import CompositeEvaluator
from model.enum.condition_enum import ConditionType, ControlActionType, ControlPolicyType
from schema.constraint_schema import ConstraintConfigSchema, InstanceConfig
from schema.control_condition_schema import ConditionSchema, ControlActionSchema
from schema.control_config_schema import ControlConfig
from schema.policy_schema import PolicyConfig

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

    def evaluate(self, model: str, slave_id: str, snapshot: dict[str, float]) -> list[ControlActionSchema]:
        """
        Evaluate control conditions and return all matching actions in priority order.

        Execution Mode: Cumulative with Priority Protection
        - Collects all triggered rules.
        - Executes actions from all rules in priority order (lower number = higher priority).
        - Higher priority actions protect their writes from being overwritten by lower priority ones.
        - Supports blocking: if a rule has blocking=True, stops processing remaining rules.
        """
        condition_list: list[ConditionSchema] = self.control_config.get_control_list(model, slave_id)

        # Step 1: Collect all triggered rules
        triggered_rule_list: list[ConditionSchema] = []
        get_value_by_snapshot: Callable[[str], float | None] = partial(self.get_snapshot_value, snapshot)

        for rule in condition_list:
            if rule.composite is None or rule.composite.invalid:
                continue

            is_matched: bool = self.composite_evaluator.evaluate_composite_node(rule.composite, get_value_by_snapshot)
            if is_matched:
                triggered_rule_list.append(rule)

        if not triggered_rule_list:
            return []

        # Step 2: Sort by priority (lower number = higher priority)
        triggered_rule_list.sort(
            key=lambda r: (r.priority is None, r.priority if r.priority is not None else float("inf"))
        )

        # Pretty-print matched rules summary
        self._pretty_log_matched_rules(model, slave_id, triggered_rule_list, snapshot)

        # Step 3: Process each rule and collect actions
        result_action_list: list[ControlActionSchema] = []

        for rule in triggered_rule_list:
            # Build composite summary once for this rule
            try:
                composite_summary = (
                    self.composite_evaluator.build_composite_reason_summary(rule.composite)
                    if rule.composite
                    else "composite"
                )
            except Exception:
                composite_summary = "composite"

            rule_actions_processed = 0
            for action in rule.actions:
                if not action.model or not action.slave_id or action.type is None:
                    logger.warning(
                        f"[EVAL] Skip action in rule '{rule.code}' (p={rule.priority}) "
                        f"due to missing action fields (model/slave_id/type)"
                    )
                    continue

                # Apply policy or emergency override
                if action.emergency_override:
                    processed_action: ControlActionSchema | None = self._handle_emergency_override(action)
                else:
                    processed_action: ControlActionSchema | None = self._apply_policy_to_action(
                        condition=rule, action=action, snapshot=snapshot
                    )

                if processed_action is None:
                    logger.warning(
                        f"[EVAL] Skip action in rule '{rule.code}' (p={rule.priority}) "
                        f"due to policy processing failure"
                    )
                    continue

                processed_action.priority = rule.priority

                # Build reason string
                action_desc = f"{action.model}_{action.slave_id}:{action.type.value}"
                base_reason = f"[{rule.code}] {rule.name} | {composite_summary} | priority={rule.priority}"

                if action.emergency_override and processed_action.reason:
                    processed_action.reason = f"{processed_action.reason} | {base_reason} | {action_desc}"
                else:
                    processed_action.reason = f"{base_reason} | {action_desc}"

                result_action_list.append(processed_action)
                rule_actions_processed += 1

            # Rule-level execution log
            if rule_actions_processed > 0:
                logger.info(
                    f"[EVAL] Execute '{rule.code}' (priority={rule.priority}): {rule_actions_processed} action(s)"
                )
            else:
                logger.warning(
                    f"[EVAL] Rule '{rule.code}' (priority={rule.priority}) triggered but produced no valid actions"
                )

            # Blocking rule handling
            if rule.blocking:
                remaining_count: int = len(triggered_rule_list) - (triggered_rule_list.index(rule) + 1)
                if remaining_count > 0:
                    remaining_code_list: list[str] = [
                        rule.code for rule in triggered_rule_list[triggered_rule_list.index(rule) + 1 :]
                    ]
                    logger.info(
                        f"[EVAL] Rule '{rule.code}' blocking=True, "
                        f"skip {remaining_count} remaining rules: {remaining_code_list}"
                    )
                break

        # Summary log
        if result_action_list:
            logger.info(
                f"[EVAL] Total {len(result_action_list)} action(s) from {len(triggered_rule_list)} rule(s) "
                f"for {model}_{slave_id}"
            )
        else:
            logger.warning(
                f"[EVAL] {len(triggered_rule_list)} rule(s) triggered but no valid actions produced "
                f"for {model}_{slave_id}"
            )

        return result_action_list

    def _apply_policy_to_action(
        self, condition: ConditionSchema, action: ControlActionSchema, snapshot: dict[str, float]
    ) -> ControlActionSchema | None:
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
            if not policy.sources or len(policy.sources) != 1:
                logger.warning(f"[EVAL] THRESHOLD policy requires exactly 1 source")
                return None
            return snapshot.get(policy.sources[0])

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
        self, action: ControlActionSchema, policy: PolicyConfig, snapshot: dict[str, float]
    ) -> ControlActionSchema | None:
        if not policy.sources or len(policy.sources) != 1:
            logger.warning(f"[EVAL] ABSOLUTE_LINEAR requires exactly 1 source")
            return None

        temp_value = snapshot.get(policy.sources[0])
        if temp_value is None:
            logger.warning(f"[EVAL] Cannot get temperature value for {policy.sources[0]}")
            return None

        # Validate required fields
        if policy.base_temp is None:
            logger.warning(f"[EVAL] ABSOLUTE_LINEAR missing base_temp")
            return None

        # Calculate target frequency: base_freq + (temp - base_temp) * gain
        target_freq = policy.base_freq + (temp_value - policy.base_temp) * policy.gain_hz_per_unit

        new_action: ControlActionSchema = action.model_copy()
        new_action.value = target_freq
        new_action.type = ControlActionType.SET_FREQUENCY  # Absolute setting
        logger.info(
            f"[EVAL] Absolute linear: temp={temp_value}°C, base_temp={policy.base_temp}°C, target_freq={target_freq}Hz"
        )
        return new_action

    def _apply_incremental_linear_policy(
        self, action: ControlActionSchema, policy: PolicyConfig, snapshot: dict[str, float]
    ) -> ControlActionSchema | None:
        # Temperature difference control
        condition_value = self._get_condition_value(policy, snapshot)  # Calculate temperature difference
        if condition_value is None:
            logger.warning(f"[EVAL] Cannot get condition value for incremental_linear policy")
            return None

        adjustment = policy.gain_hz_per_unit

        new_action: ControlActionSchema = action.model_copy()
        new_action.type = ControlActionType.ADJUST_FREQUENCY  # Incremental adjustment
        new_action.value = adjustment
        logger.info(f"[EVAL] Incremental linear: temp_diff={condition_value}°C, adjustment={adjustment}Hz")
        return new_action

    # TODO: Maybe Need to update to support other action types in future
    def _handle_emergency_override(self, action: ControlActionSchema) -> ControlActionSchema | None:
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

    # TODO: Maybe Need to update to support other constraint types in future
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

    def _pretty_line(self, is_last: bool, text: str) -> str:
        """Return ASCII tree-style indentation line (no symbols or emojis)."""
        prefix = " └─" if is_last else " ├─"
        return f"{prefix} {text}"

    def _pretty_log_matched_rules(
        self,
        model: str,
        slave_id: str,
        matched_rules: list[ConditionSchema],
        snapshot: dict[str, float],
    ) -> None:
        """
        Print a human-readable summary for all matched rules.
        - No emojis or special characters.
        - Lists Rule / Priority / Status / Source summary / Action summary.
        """
        try:
            number_of_total_rule: int = len(self.control_config.get_control_list(model, slave_id))
        except Exception:
            number_of_total_rule = None

        total_rules_str = f"{number_of_total_rule}" if number_of_total_rule is not None else "?"
        logger.info(f"[EVAL][{model}_{slave_id}] Matched {len(matched_rules)} / {total_rules_str} rules")

        for idx, rule in enumerate(matched_rules):
            is_last = idx == len(matched_rules) - 1
            rule_head = f"Rule: {rule.code:<28} | priority={rule.priority if rule.priority is not None else '-':<3} | status=TRIGGERED"
            logger.info(self._pretty_line(is_last, rule_head))

            # Build condition summary
            try:
                comp_summary = (
                    self.composite_evaluator.build_composite_reason_summary(rule.composite)
                    if rule.composite
                    else "composite"
                )
            except Exception:
                comp_summary = "composite"

            # Attempt to include measurement values if available
            policy: PolicyConfig | None = rule.policy
            if policy and policy.condition_type:
                if policy.condition_type == ConditionType.THRESHOLD and policy.sources and len(policy.sources) == 1:
                    src = policy.sources[0]
                    mv = snapshot.get(src)
                    cond_line = f"Source: {src} = {mv if mv is not None else 'NA'} | {comp_summary}"
                elif policy.condition_type == ConditionType.DIFFERENCE and policy.sources and len(policy.sources) == 2:
                    s1, s2 = policy.sources
                    v1, v2 = snapshot.get(s1), snapshot.get(s2)
                    if (v1 is not None) and (v2 is not None):
                        dt = v1 - v2
                        cond_line = f"Sources: {s1}={v1}, {s2}={v2} -> Δ={dt} | {comp_summary}"
                    else:
                        cond_line = f"Sources: {s1}={v1}, {s2}={v2} | {comp_summary}"
                else:
                    cond_line = f"Condition: {comp_summary}"
            else:
                cond_line = f"Condition: {comp_summary}"

            logger.info(" │   " + cond_line)

            # List all actions for the rule
            if not rule.actions:
                logger.info(" │   Action: (none)")
            else:
                for action in rule.actions:
                    a_model = action.model or "-"
                    a_sid = action.slave_id or "-"
                    a_type = action.type.value if action.type else "-"
                    a_target = action.target or "-"
                    a_value = action.value if action.value is not None else "-"
                    logger.info(f" │   Action: {a_model}_{a_sid}:{a_type} target={a_target} value={a_value}")

            if not is_last:
                logger.info(" │")
