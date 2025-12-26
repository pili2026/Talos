from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from core.model.enum.condition_enum import ConditionOperator, ConditionType
from core.schema.control_condition_schema import CompositeNode
from repository.control_execution_store import ControlExecutionStore

logger = logging.getLogger(__name__)


Number = float | int
ValueGetter = Callable[[str], Number | None]  # e.g., lambda key: snapshot.get(key)


class CompositeEvaluator:
    """
    Composite condition evaluator (class-based version)
    - Supports any / all / not groups
    - Supports threshold / difference / aggregate / time_elapsed leaf nodes
    - EQUAL uses strict equality by default; an optional comparison_tolerance can be set
    - Supports optional hysteresis (float) and debounce_sec (int) on leaf nodes
    """

    def __init__(
        self,
        *,
        comparison_tolerance: float | None = None,
        execution_store: ControlExecutionStore = None,  # ControlExecutionStore for time_elapsed
        timezone: str = "Asia/Taipei",  # Timezone for time calculations
    ):
        """
        :param comparison_tolerance: If provided, EQUAL treats |a-b| <= comparison_tolerance as equal;
                                     if None, strict equality is used.
        :param execution_store: ControlExecutionStore for time_elapsed condition persistence
        :param timezone: Timezone for time calculations
        """
        self.comparison_tolerance = comparison_tolerance
        self.execution_store = execution_store
        self.timezone = timezone

        # Maintain minimal state per leaf object (using id(node)): is_true / pending_since
        # key: int(id(node)) → {"is_true": bool, "pending_since": float|None}
        self._leaf_states: dict[int, dict[str, float | bool | None]] = {}

        # Context for current evaluation (rule_code, device info)  ← ADDED
        self._current_context: dict[str, str] = {}

    def set_evaluation_context(self, rule_code: str, device_model: str, device_slave_id: str):
        """
        Set context for current evaluation.
        Must be called before evaluate_composite_node() for rules with time_elapsed conditions.

        Args:
            rule_code: Unique rule code (e.g., "FREQ_STEPDOWN_4H")
            device_model: Device model (e.g., "TECO_VFD")
            device_slave_id: Device slave ID (e.g., "4")
        """
        self._current_context = {
            "rule_code": rule_code,
            "device_model": device_model,
            "device_slave_id": device_slave_id,
        }

    def evaluate_composite_node(self, node: CompositeNode, get_value: ValueGetter) -> bool:
        """Recursively evaluate whether a CompositeNode is satisfied."""
        if node is None:
            return False

        # Leaf node
        if node.type == ConditionType.THRESHOLD:
            return self._evaluate_threshold_leaf(node, get_value)

        if node.type == ConditionType.DIFFERENCE:
            return self._evaluate_difference_leaf(node, get_value)

        if node.type in {
            ConditionType.AVERAGE,
            ConditionType.SUM,
            ConditionType.MIN,
            ConditionType.MAX,
        }:
            return self._evaluate_aggregate_leaf(node, get_value)

        if node.type == ConditionType.TIME_ELAPSED:
            return self._evaluate_time_elapsed_leaf(node)

        # Group node (only one exists at a time)
        if node.all is not None:
            return all(self.evaluate_composite_node(child, get_value) for child in node.all)

        if node.any is not None:
            return any(self.evaluate_composite_node(child, get_value) for child in node.any)

        if node.not_ is not None:
            return not self.evaluate_composite_node(node.not_, get_value)

        return False

    def build_composite_reason_summary(self, node: CompositeNode) -> str:
        """Output a human-readable summary string (useful for action.reason)."""
        if node.type == ConditionType.THRESHOLD:
            sensor: str = node.sources[0] if node.sources and len(node.sources) > 0 else "unknown"

            if node.operator == ConditionOperator.BETWEEN:
                return f"threshold({sensor} between {node.min}..{node.max})"
            return f"threshold({sensor} {node.operator.value.lower()} {node.threshold})"

        if node.type == ConditionType.DIFFERENCE:
            srcs = ",".join(node.sources or [])
            if node.operator == ConditionOperator.BETWEEN:
                return f"difference([{srcs}] between {node.min}..{node.max}{' abs' if node.abs else ''})"
            return f"difference([{srcs}] {node.operator.value.lower()} {node.threshold}{' abs' if node.abs else ''})"

        if node.type in {
            ConditionType.AVERAGE,
            ConditionType.SUM,
            ConditionType.MIN,
            ConditionType.MAX,
        }:
            srcs: str = ",".join(node.sources or [])
            agg_type = node.type.value  # 'average', 'sum', 'min', 'max'

            if node.operator == ConditionOperator.BETWEEN:
                return f"{agg_type}([{srcs}]) between {node.min}..{node.max}"
            return f"{agg_type}([{srcs}]) {node.operator.value.lower()} {node.threshold}"

        if node.type == ConditionType.TIME_ELAPSED:
            return f"time_elapsed(interval={node.interval_hours}h)"

        if node.any is not None:
            # OR Logic: recursively process sub-nodes
            sub_reasons = []
            for sub_node in node.any:
                sub_reason = self.build_composite_reason_summary(sub_node)
                if sub_reason:
                    sub_reasons.append(sub_reason)

            if sub_reasons:
                return f"({' OR '.join(sub_reasons)})"
            else:
                return "any(conditions)"

        if node.all is not None:
            # AND Logic: recursively process sub-nodes
            sub_reasons = []
            for sub_node in node.all:
                sub_reason = self.build_composite_reason_summary(sub_node)
                if sub_reason:
                    sub_reasons.append(sub_reason)

            if sub_reasons:
                return f"({' AND '.join(sub_reasons)})"
            else:
                return "all(conditions)"

        if node.not_ is not None:
            # NOT Logic: recursively process single sub-node
            sub_reason = self.build_composite_reason_summary(node.not_)
            if sub_reason:
                return f"NOT({sub_reason})"
            else:
                return "not(condition)"

        # Unknown node type
        return f"unknown_condition(type={node.type})"

    def _evaluate_threshold_leaf(self, node: CompositeNode, get_value: ValueGetter) -> bool:
        """Evaluate whether a threshold-type leaf node is satisfied."""
        if not node.sources or len(node.sources) != 1:
            return False

        value = get_value(node.sources[0])
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return False

        try:
            numeric_value = float(value)
        except Exception:
            return False

        raw_true = self._evaluate_operator_comparison(
            operator=node.operator,
            value=numeric_value,
            threshold=node.threshold,
            min_value=node.min,
            max_value=node.max,
        )

        # Add stabilization (hysteresis + debounce) using id(node) as the state key
        return self._stabilize_leaf_truth(
            key=id(node),
            operator=node.operator,
            value=numeric_value,
            raw_true=raw_true,
            threshold=node.threshold,
            min_value=node.min,
            max_value=node.max,
            hysteresis=float(node.hysteresis or 0.0),
            debounce_sec=float(node.debounce_sec or 0.0),
        )

    def _evaluate_difference_leaf(self, node: CompositeNode, get_value: ValueGetter) -> bool:
        """Evaluate whether a difference-type leaf node is satisfied."""
        if not node.sources or len(node.sources) != 2:
            return False

        v1, v2 = get_value(node.sources[0]), get_value(node.sources[1])
        if v1 is None or v2 is None:
            return False
        if (isinstance(v1, float) and math.isnan(v1)) or (isinstance(v2, float) and math.isnan(v2)):
            return False

        try:
            diff = float(v1) - float(v2)
        except Exception:
            return False

        if node.abs:
            diff = abs(diff)

        raw_true = self._evaluate_operator_comparison(
            operator=node.operator,
            value=diff,
            threshold=node.threshold,
            min_value=node.min,
            max_value=node.max,
        )

        # Apply stabilization as well
        return self._stabilize_leaf_truth(
            key=id(node),
            operator=node.operator,
            value=diff,
            raw_true=raw_true,
            threshold=node.threshold,
            min_value=node.min,
            max_value=node.max,
            hysteresis=float(node.hysteresis or 0.0),
            debounce_sec=float(node.debounce_sec or 0.0),
        )

    def _evaluate_operator_comparison(
        self,
        *,
        operator: ConditionOperator,
        value: Number,
        threshold: Number | None = None,
        min_value: Number | None = None,
        max_value: Number | None = None,
    ) -> bool:
        """Compare a value based on the operator; EQUAL supports optional comparison_tolerance."""
        if operator == ConditionOperator.GREATER_THAN:
            return threshold is not None and value > threshold

        if operator == ConditionOperator.GREATER_THAN_OR_EQUAL:
            return threshold is not None and value >= threshold

        if operator == ConditionOperator.LESS_THAN:
            return threshold is not None and value < threshold

        if operator == ConditionOperator.LESS_THAN_OR_EQUAL:
            return threshold is not None and value <= threshold

        if operator == ConditionOperator.EQUAL:
            if threshold is None:
                return False
            if self.comparison_tolerance is None:
                return value == threshold
            return abs(value - threshold) <= self.comparison_tolerance

        if operator == ConditionOperator.BETWEEN:
            return (min_value is not None) and (max_value is not None) and (min_value <= value <= max_value)

        return False

    def _evaluate_aggregate_leaf(self, node: CompositeNode, get_value: ValueGetter) -> bool:
        """
        Evaluate aggregate condition (AVERAGE, SUM, MIN, MAX).

        Aggregates multiple source values and compares against threshold.
        Handles missing values gracefully by skipping None values.
        Returns False if no valid values are found.
        """
        if not node.sources or len(node.sources) < 2:
            return False

        # Collect all valid values (skip None and NaN)
        values = []
        for src in node.sources:
            val = get_value(src)
            if val is not None:
                # Also check for NaN
                if isinstance(val, float) and math.isnan(val):
                    continue
                values.append(val)

        # No valid values → condition fails
        if not values:
            return False

        # Calculate aggregated value
        try:
            if node.type == ConditionType.AVERAGE:
                aggregated = sum(values) / len(values)
            elif node.type == ConditionType.SUM:
                aggregated = sum(values)
            elif node.type == ConditionType.MIN:
                aggregated = min(values)
            elif node.type == ConditionType.MAX:
                aggregated = max(values)
            else:
                # Unknown aggregate type
                return False

            # Convert to float for comparison
            aggregated = float(aggregated)
        except Exception:
            return False

        # First do raw comparison without stabilization
        raw_true: bool = self._evaluate_operator_comparison(
            operator=node.operator,
            value=aggregated,
            threshold=node.threshold,
            min_value=node.min,
            max_value=node.max,
        )

        # Apply stabilization (hysteresis + debounce) using id(node) as the state key
        return self._stabilize_leaf_truth(
            key=id(node),
            operator=node.operator,
            value=aggregated,
            raw_true=raw_true,
            threshold=node.threshold,
            min_value=node.min,
            max_value=node.max,
            hysteresis=float(node.hysteresis or 0.0),
            debounce_sec=float(node.debounce_sec or 0.0),
        )

    # ====== TIME_ELAPSED leaf ======  ← ADDED

    def _evaluate_time_elapsed_leaf(self, node: CompositeNode) -> bool:
        """
        Evaluate time_elapsed condition.

        Returns True if interval has elapsed since last execution.
        Uses execution_store for persistence across restarts.

        Args:
            node: CompositeNode with type=TIME_ELAPSED and interval_hours set

        Returns:
            True if interval has elapsed, False otherwise
        """
        if self.execution_store is None:
            logger.error("[EVAL] time_elapsed: execution_store not initialized")
            return False

        if node.interval_hours is None or node.interval_hours <= 0:
            logger.error("[EVAL] time_elapsed: invalid interval_hours")
            return False

        # Get context (set by ControlEvaluator before evaluation)
        rule_code = self._current_context.get("rule_code", "<unknown>")
        device_model = self._current_context.get("device_model", "<unknown>")
        device_slave_id = self._current_context.get("device_slave_id", "<unknown>")

        try:

            tz = ZoneInfo(self.timezone)
            now = datetime.now(tz)

            # Get last execution time
            last_execution: datetime | None = self.execution_store.get_last_execution(rule_code)

            # First execution: trigger immediately
            if last_execution is None:
                logger.info(
                    f"[EVAL] time_elapsed: '{rule_code}' first execution " f"for {device_model}_{device_slave_id}"
                )
                self.execution_store.update_execution(rule_code, now, device_model, device_slave_id)
                return True

            # Calculate elapsed time
            elapsed_hours = (now - last_execution).total_seconds() / 3600

            # Check if interval has elapsed
            if elapsed_hours >= node.interval_hours:
                next_execution = last_execution.replace(microsecond=0) + timedelta(hours=node.interval_hours)

                logger.info(
                    f"[EVAL] time_elapsed: '{rule_code}' triggered "
                    f"(elapsed={elapsed_hours:.2f}h, interval={node.interval_hours}h)"
                )
                logger.info(
                    f"[EVAL] Last: {last_execution.strftime('%Y-%m-%d %H:%M:%S')}, "
                    f"Next: {next_execution.strftime('%Y-%m-%d %H:%M:%S')}"
                )

                # Update execution time
                self.execution_store.update_execution(rule_code, now, device_model, device_slave_id)
                return True

            # Not yet time
            remaining_hours: float = node.interval_hours - elapsed_hours
            next_execution: datetime = last_execution + timedelta(hours=node.interval_hours)

            logger.debug(
                f"[EVAL] time_elapsed: '{rule_code}' not triggered "
                f"(elapsed={elapsed_hours:.2f}h, remaining={remaining_hours:.2f}h)"
            )
            logger.debug(
                f"[EVAL] Next execution in {remaining_hours:.2f}h " f"at {next_execution.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            return False

        except Exception as e:
            logger.error(f"[EVAL] time_elapsed error: {e}", exc_info=True)
            return False

    # ====== Added: minimal implementation of hysteresis + debounce ======

    def _stabilize_leaf_truth(
        self,
        *,
        key: int,
        operator: ConditionOperator,
        value: float,
        raw_true: bool,
        threshold: float | None,
        min_value: float | None,
        max_value: float | None,
        hysteresis: float,
        debounce_sec: int,
    ) -> bool:
        """
        Apply hysteresis based on the previous state, then debounce. Return the stabilized boolean.
        """
        st = self._leaf_states.setdefault(key, {"is_true": False, "pending_since": None})
        hold = bool(st["is_true"])

        # 1) Hysteresis (enabled only if defined)
        if hysteresis > 0.0:
            if operator == ConditionOperator.GREATER_THAN and threshold is not None:
                raw_true = (value >= threshold - hysteresis) if hold else (value > threshold)
            elif operator == ConditionOperator.GREATER_THAN_OR_EQUAL and threshold is not None:
                raw_true = (value >= threshold - hysteresis) if hold else (value >= threshold)
            elif operator == ConditionOperator.LESS_THAN and threshold is not None:
                raw_true = (value <= threshold + hysteresis) if hold else (value < threshold)
            elif operator == ConditionOperator.LESS_THAN_OR_EQUAL and threshold is not None:
                raw_true = (value <= threshold + hysteresis) if hold else (value <= threshold)
            elif operator == ConditionOperator.BETWEEN and (min_value is not None) and (max_value is not None):
                low_value: float = min_value
                high_value: float = max_value
                if hold:
                    raw_true = (low_value - hysteresis) <= value <= (high_value + hysteresis)
                else:
                    raw_true = low_value <= value <= high_value
            elif operator == ConditionOperator.EQUAL and threshold is not None:
                eps = self.comparison_tolerance or 1e-9
                raw_true = (abs(value - threshold) <= (eps + hysteresis)) if hold else (abs(value - threshold) <= eps)
            # Other operators keep original logic

        # 2) Debounce (must remain true continuously for debounce_sec)
        if debounce_sec > 0:
            now = time.monotonic()
            if raw_true:
                if st["pending_since"] is None:
                    st["pending_since"] = now
                    st["is_true"] = False
                    return False
                if (now - float(st["pending_since"])) >= debounce_sec:
                    st["is_true"] = True
                    return True
                # Not yet reached the threshold duration
                st["is_true"] = False
                return False

            # Interrupted: reset timer and set false
            st["pending_since"] = None
            st["is_true"] = False
            return False

        # No debounce: use (hysteresis-adjusted) raw_true and keep pending_since only when true
        st["pending_since"] = None if not raw_true else st["pending_since"]
        st["is_true"] = bool(raw_true)
        return st["is_true"]
