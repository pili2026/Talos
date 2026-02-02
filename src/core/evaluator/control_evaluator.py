import logging
import math
from datetime import datetime, time
from functools import partial
from typing import Callable
from zoneinfo import ZoneInfo

from core.evaluator.composite_evaluator import CompositeEvaluator
from core.model.control_composite import CompositeNode
from core.model.device_constant import DEFAULT_MISSING_VALUE
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

    def get_snapshot_value(self, global_snapshot: dict[str, dict[str, float]], source: Source) -> float | None:
        """
        Fetch numeric value from global snapshot using Source object.

        Args:
            global_snapshot: Global snapshot data (device_id -> {pin -> value})
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

        device_id = f"{source.device}_{source.slave_id}"
        device_snapshot: dict[str, float] | None = global_snapshot.get(device_id)
        if device_snapshot is None:
            logger.debug(f"[EVAL] Device {device_id} not found in global snapshot")
            return None

        # Collect values from snapshot (with validation)
        values: list[float] = []
        for pin in pins:
            raw_value: float | None = device_snapshot.get(pin)

            # Skip None values
            if raw_value is None:
                logger.debug(f"[EVAL] Pin {pin} is None, skipping")
                continue

            # Convert to float
            try:
                value_float = float(raw_value)
            except (TypeError, ValueError):
                logger.warning(f"[EVAL] Invalid value for pin {pin}: {raw_value}")
                continue

            if value_float == DEFAULT_MISSING_VALUE:
                logger.debug(
                    f"[EVAL] Pin {pin} is DEFAULT_MISSING_VALUE({DEFAULT_MISSING_VALUE}), " f"treated as missing"
                )
                continue

            if math.isnan(value_float):
                logger.debug(f"[EVAL] Pin {pin} is NaN, treated as missing")
                continue

            # Valid value, add to list
            values.append(value_float)

        # No valid values collected
        if not values:
            logger.debug(f"[EVAL] Source {source} has no valid values after filtering " f"(all pins were None/-1/NaN)")
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

    def evaluate(self, model: str, slave_id: str, snapshot: dict[str, dict[str, float]]) -> list[ControlActionSchema]:
        """
        Evaluate control conditions and return all matching actions in priority order.

        Execution Mode: Cumulative with Priority Protection
        - Collects all triggered rules.
        - Executes actions from all rules in priority order (lower number = higher priority).
        - Higher priority actions protect their writes from being overwritten by lower priority ones.
        - Supports blocking: if a rule has blocking=True, stops processing remaining rules.
        """
        condition_list: list[ConditionSchema] = self.control_config.get_control_list(model, slave_id)
        logger.info("=" * 80)
        logger.info(f"[EVAL] Starting evaluation for {model}_{slave_id}")
        logger.info(f"[EVAL] Total controls: {len(condition_list)}")
        logger.info("=" * 80)

        # Step 1: Collect all triggered rules
        triggered_rule_list: list[ConditionSchema] = []
        get_value_by_snapshot: Callable[[str], float | None] = partial(self.get_snapshot_value, snapshot)

        # Get current time for time-based conditions
        datetime_now = datetime.now(self.timezone)

        for rule in condition_list:
            logger.info(f"[EVAL] Checking: {rule.code} (priority={rule.priority})")

            if rule.composite is None or rule.composite.invalid:
                logger.info("[EVAL]   └─ SKIP: Invalid composite")
                continue

            # Check time-based activation

            if not self._is_time_active(rule, datetime_now):
                logger.info(f"[EVAL] [{model}_{slave_id}] Skip '{rule.code}': " f"outside active time ranges")
                continue

            # Set evaluation context before evaluating
            self.composite_evaluator.set_evaluation_context(rule.code, model, slave_id)

            is_matched: bool = self.composite_evaluator.evaluate_composite_node(rule.composite, get_value_by_snapshot)

            logger.info(f"[EVAL]   └─ Condition met: {is_matched}")

            if is_matched:
                triggered_rule_list.append(rule)

        if not triggered_rule_list:
            return []

        # Step 2: Sort by priority (lower number = higher priority)
        triggered_rule_list.sort(
            key=lambda r: (r.priority is None, r.priority if r.priority is not None else float("inf"))
        )

        # Pretty-print matched rules summary
        self._pretty_log_matched_rules(model=model, slave_id=slave_id, matched_rules=triggered_rule_list)

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

        logger.info("=" * 80)
        logger.info(f"[EVAL] Final result: {len(result_action_list)} action(s)")
        for i, action in enumerate(result_action_list):
            logger.info(
                f"[EVAL]   Action {i+1}: {action.model}_{action.slave_id}.{action.target} = {action.value} "
                f"(type={action.type}, priority={action.priority})"
            )
        logger.info("=" * 80)

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
        self, condition: ConditionSchema, action: ControlActionSchema, snapshot: dict[str, dict[str, float]]
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

    def _apply_absolute_linear_policy(
        self,
        condition: ConditionSchema,
        action: ControlActionSchema,
        policy: PolicyConfig,
        snapshot: dict[str, dict[str, float]],
    ) -> ControlActionSchema | None:
        """
        Apply absolute linear policy using condition reference.

        Formula: target_freq = base_freq + (condition_value - base_value) * gain
        """
        # Validate required fields
        if policy.base_freq is None or policy.base_value is None or policy.gain_hz_per_unit is None:
            logger.warning("[EVAL] ABSOLUTE_LINEAR missing required fields (base_freq/base_value/gain)")
            return None

        if not policy.input_source:
            logger.warning("[EVAL] ABSOLUTE_LINEAR policy missing 'input_source' field")
            return None

        # Find condition by ID
        condition_node = self._find_condition_by_id(condition.composite, policy.input_source)
        if not condition_node:
            logger.error(f"[EVAL] Condition ID '{policy.input_source}' not found in composite tree")
            return None

        # Evaluate condition value
        condition_value = self._evaluate_condition_value(condition_node, snapshot)
        if condition_value is None:
            logger.warning(f"[EVAL] Cannot evaluate condition '{policy.input_source}'")
            return None
        # =================================================

        # Calculate target frequency
        target_freq: float = policy.base_freq + (condition_value - policy.base_value) * policy.gain_hz_per_unit

        new_action: ControlActionSchema = action.model_copy()
        new_action.value = target_freq
        new_action.type = ControlActionType.SET_FREQUENCY

        logger.info(
            f"[EVAL] Absolute linear: input_source='{policy.input_source}' "
            f"value={condition_value:.2f}, base_value={policy.base_value}°C, "
            f"target_freq={target_freq:.2f}Hz"
        )
        return new_action

    def _apply_incremental_linear_policy(
        self,
        condition: ConditionSchema,
        action: ControlActionSchema,
        policy: PolicyConfig,
        snapshot: dict[str, dict[str, float]],
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

        if not policy.input_source:
            logger.warning("[EVAL] INCREMENTAL_LINEAR policy missing 'input_source' field")
            return None

        # Find condition by ID
        condition_node = self._find_condition_by_id(condition.composite, policy.input_source)
        if not condition_node:
            logger.error(f"[EVAL] Condition ID '{policy.input_source}' not found in composite tree")
            return None

        # Evaluate condition value (for logging purposes)
        condition_value = self._evaluate_condition_value(condition_node, snapshot)
        # =================================================

        adjustment = policy.gain_hz_per_unit

        new_action = action.model_copy()
        new_action.type = ControlActionType.ADJUST_FREQUENCY
        new_action.value = adjustment

        logger.info(
            f"[EVAL] Incremental linear: input_source='{policy.input_source}' "
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
        """Print a human-readable summary for all matched rules (v2.0)"""
        try:
            total_rule_count = len(self.control_config.get_control_list(model, slave_id))
        except Exception:
            total_rule_count = None

        total_str = str(total_rule_count) if total_rule_count is not None else "?"
        logger.info(f"[EVAL][{model}_{slave_id}] Matched {len(matched_rules)} / {total_str} rules")

        for idx, rule in enumerate(matched_rules):
            is_last = idx == len(matched_rules) - 1
            rule_header = (
                f"Rule: {rule.code:<28} | "
                f"priority={rule.priority if rule.priority is not None else '-':<3} | "
                f"status=TRIGGERED"
            )
            logger.info(self._pretty_line(is_last, rule_header))

            # Build composite summary
            try:
                comp_summary = (
                    self.composite_evaluator.build_composite_reason_summary(rule.composite)
                    if rule.composite
                    else "composite"
                )
            except Exception:
                comp_summary = "composite"

            logger.info(f" │   Condition: {comp_summary}")

            # Policy info (v2.0 format)
            policy = rule.policy
            if policy and policy.type != ControlPolicyType.DISCRETE_SETPOINT:
                if policy.input_source:
                    logger.info(f" │   Policy: {policy.type.value} using input_source='{policy.input_source}'")
                else:
                    logger.info(f" │   Policy: {policy.type.value} (missing input reference)")

            # List actions
            if not rule.actions:
                logger.info(" │   Action: (none)")
            else:
                for action in rule.actions:
                    a_model = action.model or "-"
                    a_sid = action.slave_id or "-"
                    a_type = action.type.value if action.type else "-"
                    a_target = action.target or "-"
                    a_value = action.value if action.value is not None else "-"
                    logger.info(f" │   Action: {a_model}_{a_sid}:{a_type} " f"target={a_target} value={a_value}")

            if not is_last:
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

    def _evaluate_condition_value(
        self, condition: CompositeNode, snapshot: dict[str, dict[str, float]]
    ) -> float | None:
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
