import logging
import math
from datetime import datetime, time
from functools import partial
from typing import Callable
from zoneinfo import ZoneInfo

from core.evaluator.composite_evaluator import CompositeEvaluator
from core.model.device_constant import DEFAULT_MISSING_VALUE
from core.model.enum.condition_enum import ConditionType, ControlActionType, ControlPolicyType
from core.model.control_composite import CompositeNode
from core.model.enum.condition_enum import AggregationType, ConditionType, ControlActionType, ControlPolicyType
from core.schema.constraint_schema import ConstraintConfigSchema, InstanceConfig
from core.schema.control_condition_schema import ConditionSchema, ControlActionSchema
from core.schema.control_condition_source_schema import Source
from core.schema.control_config_schema import ControlConfig
from core.schema.policy_schema import PolicyConfig
from core.util.time_util import TIMEZONE_INFO
from repository.control_execution_store import ControlExecutionStore

logger = logging.getLogger(__name__)


class ControlEvaluator:
    """Evaluates control conditions against snapshots and determines actions"""

    def __init__(
        self,
        control_config: ControlConfig,
        constraint_config_schema: ConstraintConfigSchema,
        execution_store: ControlExecutionStore = None,
        timezone: ZoneInfo | None = TIMEZONE_INFO,
    ):
        self.control_config = control_config
        self.constraint_config_schema = constraint_config_schema
        self.composite_evaluator = CompositeEvaluator(execution_store=execution_store)
        self.timezone = timezone

    def get_snapshot_value(self, snapshot: dict[str, float], key: str) -> float | None:
        """Fetch a numeric value by key from the given snapshot."""
        v = snapshot.get(key)
        if v is None:
            return None

        try:
            value_float = float(v)
        except Exception:
            logger.warning(f"[EVAL] snapshot[{key}] not numeric: {v!r}")
            return None

        if value_float == DEFAULT_MISSING_VALUE:
            logger.debug(
                f"[EVAL] snapshot[{key}] is DEFAULT_MISSING_VALUE({DEFAULT_MISSING_VALUE}), treated as missing"
            )
            return None

        if math.isnan(value_float):
            return None

        return value_float

    def get_snapshot_value(self, snapshot: dict[str, float], source: Source) -> float | None:
        """
        Fetch numeric value from snapshot using Source object.

        Supports both single-pin and multi-pin sources with aggregation.

        Args:
            snapshot: Device snapshot data (pin -> value mapping)
            source: Source object defining device/pins/aggregation

        Returns:
            Aggregated value or None if cannot resolve
        """
        if not isinstance(source, Source):
            logger.warning(f"[EVAL] Invalid source type: {type(source).__name__}")
            return None

        pins = source.pins or []
        if not pins:
            logger.warning("[EVAL] Source has no pins")
            return None

        # Collect values from snapshot
        values: list[float] = []
        for pin in pins:
            value = snapshot.get(pin)
            if value is None:
                continue
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                logger.warning(f"[EVAL] Invalid value for pin {pin}: {value}")
                continue

        if not values:
            return None

        # Single pin - return directly
        if len(pins) == 1:
            return values[0]

        # Multi-pin - apply aggregation
        aggregation = source.get_effective_aggregation()
        if aggregation is None:
            return values[0]

        match aggregation:
            case AggregationType.AVERAGE:
                return sum(values) / len(values)
            case AggregationType.SUM:
                return sum(values)
            case AggregationType.MIN:
                return min(values)
            case AggregationType.MAX:
                return max(values)
            case AggregationType.FIRST:
                return values[0]
            case AggregationType.LAST:
                return values[-1]
            case _:
                # Fallback to average
                logger.warning(f"[EVAL] Unknown aggregation: {aggregation}, using average")
                return sum(values) / len(values)

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

        # Get current time for time-based conditions
        datetime_now = datetime.now(self.timezone)

        for rule in condition_list:
            if rule.composite is None or rule.composite.invalid:
                continue

            # Check time-based activation

            if not self._is_time_active(rule, datetime_now):
                logger.debug(f"[EVAL] [{model}_{slave_id}] Skip '{rule.code}': " f"outside active time ranges")
                continue

            # Set evaluation context before evaluating
            self.composite_evaluator.set_evaluation_context(rule.code, model, slave_id)

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
        self._pretty_log_matched_rules(model, slave_id, triggered_rule_list)

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

    # Time-based activation check
    def _is_time_active(self, rule: ConditionSchema, now: datetime) -> bool:
        """
        Check if rule is active based on time ranges

        Args:
            rule: Control condition rule
            current_time: Current datetime (timezone-aware)

        Returns:
            True if rule is active:
            - If no active_time_ranges specified → always active
            - If within any time range → active
            - Otherwise → inactive
        """
        # No time restriction → always active
        if not rule.active_time_ranges:
            return True

        current_time = now.time()

        # Check if within any time range
        for time_range in rule.active_time_ranges:
            try:
                start = time.fromisoformat(time_range.start)
                end = time.fromisoformat(time_range.end)

                # Handle overnight ranges (e.g., 22:00 - 06:00)
                if start <= end:
                    # Normal range (e.g., 09:00 - 17:00)
                    if start <= current_time <= end:
                        return True
                else:
                    # Overnight range (e.g., 22:00 - 06:00)
                    # Active if: time >= start OR time <= end
                    if current_time >= start or current_time <= end:
                        return True
            except ValueError as e:
                logger.error(
                    f"[EVAL] Invalid time range format in rule '{rule.code}': "
                    f"start='{time_range.start}', end='{time_range.end}'. Error: {e}"
                )
                continue

        # Not within any range
        return False

    # Below: All existing methods (unchanged

    def _apply_policy_to_action(
        self, condition: ConditionSchema, action: ControlActionSchema, snapshot: dict[str, float]
    ) -> ControlActionSchema | None:
        """Apply policy processing to calculate dynamic action values"""
        if condition.policy is None:
            return action

        policy: PolicyConfig = condition.policy

        if policy.type == ControlPolicyType.DISCRETE_SETPOINT:
            return action

        if policy.type == ControlPolicyType.ABSOLUTE_LINEAR:
            return self._apply_absolute_linear_policy(
                condition=condition, action=action, policy=policy, snapshot=snapshot
            )

        if policy.type == ControlPolicyType.INCREMENTAL_LINEAR:
            return self._apply_incremental_linear_policy(
                condition=condition, action=action, policy=policy, snapshot=snapshot
            )

        logger.warning(f"[EVAL] Unsupported policy type: {policy.type}")
        return action

    def _get_condition_value(self, policy: PolicyConfig, snapshot: dict[str, float]) -> float | None:
        """Get condition value based on policy type.
        Uses get_snapshot_value() to filter DEFAULT_MISSING_VALUE / NaN.
        """

        if policy.condition_type == ConditionType.THRESHOLD:
            # Single sensor value
            if not policy.sources or len(policy.sources) != 1:
                logger.warning("[EVAL] THRESHOLD policy requires exactly 1 source")
                return None

            source_value = policy.sources[0]
            return self.get_snapshot_value(snapshot, source_value)

        if policy.condition_type == ConditionType.DIFFERENCE:
            # Difference between two sensors
            if not policy.sources or len(policy.sources) != 2:
                logger.warning("[EVAL] DIFFERENCE policy requires exactly 2 sources")
                return None

            s1, s2 = policy.sources
            v1 = self.get_snapshot_value(snapshot, s1)
            v2 = self.get_snapshot_value(snapshot, s2)

            if v1 is None or v2 is None:
                return None

            return v1 - v2

        if policy.condition_type == ConditionType.AVERAGE:
            # Average of multiple sensors
            if not policy.sources or len(policy.sources) < 2:
                logger.warning("[EVAL] AVERAGE policy requires at least 2 sources")
                return None

            values: list[float] = []

            for source_value in policy.sources:
                v = self.get_snapshot_value(snapshot, source_value)
                if v is not None:
                    values.append(v)

            if not values:
                return None

            return sum(values) / len(values)

        logger.warning(f"[EVAL] Unknown condition_type: {policy.condition_type}")
        return None

    def _apply_absolute_linear_policy(
        self, condition: ConditionSchema, action: ControlActionSchema, policy: PolicyConfig, snapshot: dict[str, float]
    ) -> ControlActionSchema | None:
        """
        Apply absolute linear policy using condition reference.

        Formula: target_freq = base_freq + (condition_value - base_temp) * gain
        """
        # Validate required fields
        if policy.base_freq is None or policy.base_temp is None or policy.gain_hz_per_unit is None:
            logger.warning("[EVAL] ABSOLUTE_LINEAR missing required fields (base_freq/base_temp/gain)")
            return None

        if not policy.input_sources_id:
            logger.warning("[EVAL] ABSOLUTE_LINEAR policy missing 'input_sources_id' field")
            return None

        # Find condition by ID
        condition_node = self._find_condition_by_id(condition.composite, policy.input_sources_id)
        if not condition_node:
            logger.error(f"[EVAL] Condition ID '{policy.input_sources_id}' not found in composite tree")
            return None

        # Evaluate condition value
        condition_value = self._evaluate_condition_value(condition_node, snapshot)
        if condition_value is None:
            logger.warning(f"[EVAL] Cannot evaluate condition '{policy.input_sources_id}'")
            return None
        # =================================================

        # Calculate target frequency
        target_freq = policy.base_freq + (condition_value - policy.base_temp) * policy.gain_hz_per_unit

        new_action: ControlActionSchema = action.model_copy()
        new_action.value = target_freq
        new_action.type = ControlActionType.SET_FREQUENCY

        logger.info(
            f"[EVAL] Absolute linear: input_sources_id='{policy.input_sources_id}' "
            f"value={condition_value:.2f}, base_temp={policy.base_temp}°C, "
            f"target_freq={target_freq:.2f}Hz"
        )
        return new_action

    def _apply_incremental_linear_policy(
        self,
        condition: ConditionSchema,
        action: ControlActionSchema,
        policy: PolicyConfig,
        snapshot: dict[str, float],
    ) -> ControlActionSchema | None:
        """
        Apply incremental linear policy using condition reference.

        Formula: adjustment = gain_hz_per_unit
        (The condition value determines IF to adjust, not HOW MUCH)
        """
        # Validate required fields
        if policy.gain_hz_per_unit is None:
            logger.warning("[EVAL] INCREMENTAL_LINEAR missing gain_hz_per_unit")
            return None

        if not policy.input_sources_id:
            logger.warning("[EVAL] INCREMENTAL_LINEAR policy missing 'input_sources_id' field")
            return None

        # Find condition by ID
        condition_node = self._find_condition_by_id(condition.composite, policy.input_sources_id)
        if not condition_node:
            logger.error(f"[EVAL] Condition ID '{policy.input_sources_id}' not found in composite tree")
            return None

        # Evaluate condition value (for logging purposes)
        condition_value = self._evaluate_condition_value(condition_node, snapshot)
        # =================================================

        adjustment = policy.gain_hz_per_unit

        new_action = action.model_copy()
        new_action.type = ControlActionType.ADJUST_FREQUENCY
        new_action.value = adjustment

        logger.info(
            f"[EVAL] Incremental linear: input_sources_id='{policy.input_sources_id}' "
            f"value={condition_value if condition_value is not None else 'N/A'}, "
            f"adjustment={adjustment}Hz"
        )
        return new_action

    def _handle_emergency_override(self, action: ControlActionSchema) -> ControlActionSchema | None:
        """Handle emergency override logic: ensure the target can reach 60 Hz if needed."""
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

    def _pretty_line(self, is_last: bool, text: str) -> str:
        """Return ASCII tree-style indentation line (no symbols or emojis)."""
        prefix = " └─" if is_last else " ├─"
        return f"{prefix} {text}"

    def _pretty_log_matched_rules(self, model: str, slave_id: str, matched_rules: list[ConditionSchema]) -> None:
        """
        Print a human-readable summary for all matched rules.
        - No emojis or special characters.
        - Lists Rule / Priority / Status / Source summary / Action summary.
        - Snapshot values go through get_snapshot_value() for consistency.
        """
        try:
            total_rule_count: int = len(self.control_config.get_control_list(model, slave_id))
        except Exception:
            total_rule_count = None

        total_rule_count_str = str(total_rule_count) if total_rule_count is not None else "?"
        logger.info(f"[EVAL][{model}_{slave_id}] Matched {len(matched_rules)} / {total_rule_count_str} rules")

        for rule_index, rule in enumerate(matched_rules):
            is_last_rule = rule_index == len(matched_rules) - 1
            rule_header = (
                f"Rule: {rule.code:<28} | "
                f"priority={rule.priority if rule.priority is not None else '-':<3} | status=TRIGGERED"
            )
            logger.info(self._pretty_line(is_last_rule, rule_header))

            # Build composite summary
            try:
                composite_summary = (
                    self.composite_evaluator.build_composite_reason_summary(rule.composite)
                    if rule.composite
                    else "composite"
                )
            except Exception:
                composite_summary = "composite"

            rule_policy: PolicyConfig | None = rule.policy

            if rule_policy and rule_policy.condition_type:
                # THRESHOLD
                if (
                    rule_policy.condition_type == ConditionType.THRESHOLD
                    and rule_policy.sources
                    and len(rule_policy.sources) == 1
                ):
                    source_key = rule_policy.sources[0]
                    source_value = self.get_snapshot_value(snapshot, source_key)
                    source_value_str = str(source_value) if source_value is not None else "NA"

                    condition_line = f"Source: {source_key} = {source_value_str} | {composite_summary}"

                # DIFFERENCE
                elif (
                    rule_policy.condition_type == ConditionType.DIFFERENCE
                    and rule_policy.sources
                    and len(rule_policy.sources) == 2
                ):
                    left_source_key, right_source_key = rule_policy.sources

                    left_value = self.get_snapshot_value(snapshot, left_source_key)
                    right_value = self.get_snapshot_value(snapshot, right_source_key)

                    left_value_str = str(left_value) if left_value is not None else "NA"
                    right_value_str = str(right_value) if right_value is not None else "NA"

                    if left_value is not None and right_value is not None:
                        difference_value = left_value - right_value
                        condition_line = (
                            f"Sources: {left_source_key}={left_value_str}, "
                            f"{right_source_key}={right_value_str} -> Δ={difference_value} | {composite_summary}"
                        )
                    else:
                        condition_line = (
                            f"Sources: {left_source_key}={left_value_str}, "
                            f"{right_source_key}={right_value_str} | {composite_summary}"
                        )

                # AVERAGE
                elif (
                    rule_policy.condition_type == ConditionType.AVERAGE
                    and rule_policy.sources
                    and len(rule_policy.sources) >= 2
                ):
                    valid_values: list[float] = []
                    source_parts: list[str] = []

                    for source_key in rule_policy.sources:
                        source_value = self.get_snapshot_value(snapshot, source_key)
                        source_value_str = str(source_value) if source_value is not None else "NA"

                        source_parts.append(f"{source_key}={source_value_str}")

                        if source_value is not None:
                            valid_values.append(source_value)

                    sources_summary = ", ".join(source_parts)

                    if valid_values:
                        average_value: float = sum(valid_values) / len(valid_values)
                        condition_line = f"Sources: {sources_summary} -> AVG={average_value:.2f} | {composite_summary}"
                    else:
                        condition_line = f"Sources: {sources_summary} (all NA) | {composite_summary}"

                else:
                    condition_line = f"Condition: {composite_summary}"
            else:
                condition_line = f"Condition: {composite_summary}"

            logger.info(f" │   {condition_line}")

            # List all actions for the rule
            if not rule.actions:
                logger.info(" │   Action: (none)")
            else:
                for action in rule.actions:
                    action_model = action.model or "-"
                    action_slave_id = action.slave_id or "-"
                    action_type = action.type.value if action.type else "-"
                    action_target = action.target or "-"
                    action_value = action.value if action.value is not None else "-"

                    logger.info(
                        f" │   Action: {action_model}_{action_slave_id}:{action_type} "
                        f"target={action_target} value={action_value}"
                    )

            if not is_last_rule:
                logger.info(" │")

    def _find_condition_by_id(self, composite: CompositeNode, condition_id: str) -> CompositeNode | None:
        """
        Recursively search for a condition node by ID in composite tree.

        Args:
            composite: Root composite node to search
            condition_id: Target condition ID

        Returns:
            CompositeNode if found, None otherwise
        """
        if composite is None:
            return None

        # Check current node
        if composite.sources_id == condition_id:
            return composite

        # Search in children (group nodes)
        if composite.all:
            for child in composite.all:
                result = self._find_condition_by_id(child, condition_id)
                if result:
                    return result

        if composite.any:
            for child in composite.any:
                result = self._find_condition_by_id(child, condition_id)
                if result:
                    return result

        if composite.not_:
            result = self._find_condition_by_id(composite.not_, condition_id)
            if result:
                return result

        return None

    def _evaluate_condition_value(self, condition: CompositeNode, snapshot: dict[str, float]) -> float | None:
        """
        Evaluate a condition node and return its numeric value.

        This is used by policies to get the condition's computed value.

        Args:
            condition: Condition node to evaluate
            snapshot: Current snapshot data

        Returns:
            Computed value or None if cannot evaluate
        """
        if condition.type is None:
            logger.warning("[EVAL] Cannot evaluate condition without type")
            return None

        if not condition.sources:
            logger.warning(f"[EVAL] Condition {condition.sources_id} has no sources")
            return None

        get_value = partial(self.get_snapshot_value, snapshot)

        # Different evaluation based on condition type
        match condition.type:
            case ConditionType.THRESHOLD:
                # Single source value
                if len(condition.sources) != 1:
                    logger.warning(f"[EVAL] THRESHOLD requires 1 source, got {len(condition.sources)}")
                    return None
                return get_value(condition.sources[0])

            case ConditionType.DIFFERENCE:
                # Difference between two sources
                if len(condition.sources) != 2:
                    logger.warning(f"[EVAL] DIFFERENCE requires 2 sources, got {len(condition.sources)}")
                    return None

                v1 = get_value(condition.sources[0])
                v2 = get_value(condition.sources[1])

                if v1 is None or v2 is None:
                    return None

                diff = v1 - v2
                return abs(diff) if condition.abs else diff

            case ConditionType.AVERAGE:
                # Average of multiple sources
                if len(condition.sources) < 2:
                    logger.warning(f"[EVAL] AVERAGE requires >=2 sources, got {len(condition.sources)}")
                    return None

                values = []
                for source in condition.sources:
                    v = get_value(source)
                    if v is not None:
                        values.append(v)

                if not values:
                    return None

                return sum(values) / len(values)

            case ConditionType.SUM:
                # Sum of multiple sources
                if len(condition.sources) < 2:
                    logger.warning(f"[EVAL] SUM requires >=2 sources, got {len(condition.sources)}")
                    return None

                values = []
                for source in condition.sources:
                    v = get_value(source)
                    if v is not None:
                        values.append(v)

                if not values:
                    return None

                return sum(values)

            case ConditionType.MIN:
                # Minimum of multiple sources
                if len(condition.sources) < 2:
                    logger.warning(f"[EVAL] MIN requires >=2 sources, got {len(condition.sources)}")
                    return None

                values = []
                for source in condition.sources:
                    v = get_value(source)
                    if v is not None:
                        values.append(v)

                if not values:
                    return None

                return min(values)

            case ConditionType.MAX:
                # Maximum of multiple sources
                if len(condition.sources) < 2:
                    logger.warning(f"[EVAL] MAX requires >=2 sources, got {len(condition.sources)}")
                    return None

                values = []
                for source in condition.sources:
                    v = get_value(source)
                    if v is not None:
                        values.append(v)

                if not values:
                    return None

                return max(values)

            case _:
                logger.warning(f"[EVAL] Unsupported condition type for value evaluation: {condition.type}")
                return None
