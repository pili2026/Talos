from __future__ import annotations

import math
from typing import Callable

from model.control_model import CompositeNode
from model.enum.condition_enum import ConditionOperator, ConditionType

Number = float | int
ValueGetter = Callable[[str], Number | None]  # e.g., lambda key: snapshot.get(key)


class CompositeEvaluator:
    """
    Composite condition evaluator (class-based version)
    - Supports any / all / not groups
    - Supports threshold / difference leaf nodes
    - EQUAL uses strict equality by default; an optional comparison_tolerance can be set
    - debounce/hysteresis not yet implemented (fields are reserved but unused)
    """

    def __init__(self, *, comparison_tolerance: float | None = None):
        """
        :param comparison_tolerance: If provided, EQUAL treats |a-b| <= comparison_tolerance as equal;
                                     if None, strict equality is used.
        """
        self.comparison_tolerance = comparison_tolerance

    def evaluate_composite_node(self, node: CompositeNode, get_value: ValueGetter) -> bool:
        """Recursively evaluate whether a CompositeNode is satisfied."""
        if getattr(node, "invalid", False):
            return False

        # Leaf node
        if node.type == ConditionType.THRESHOLD:
            return self._evaluate_threshold_leaf(node, get_value)

        if node.type == ConditionType.DIFFERENCE:
            return self._evaluate_difference_leaf(node, get_value)

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
            if node.operator == ConditionOperator.BETWEEN:
                return f"threshold({node.source} between {node.min}..{node.max})"
            return f"threshold({node.source} {node.operator.value.lower()} {node.threshold})"

        if node.type == ConditionType.DIFFERENCE:
            srcs = ",".join(node.sources or [])
            if node.operator == ConditionOperator.BETWEEN:
                return f"difference([{srcs}] between {node.min}..{node.max}{' abs' if node.abs else ''})"
            return f"difference([{srcs}] {node.operator.value.lower()} {node.threshold}{' abs' if node.abs else ''})"

        if node.all is not None:
            inner = ", ".join(self.build_composite_reason_summary(c) for c in node.all)
            return f"all({inner})"
        if node.any is not None:
            inner = ", ".join(self.build_composite_reason_summary(c) for c in node.any)
            return f"any({inner})"
        if node.not_ is not None:
            return f"not({self.build_composite_reason_summary(node.not_)})"

        return "invalid"

    # ---- Internal helpers ----

    def _evaluate_threshold_leaf(self, node: CompositeNode, get_value: ValueGetter) -> bool:
        """Evaluate whether a threshold-type leaf node is satisfied."""
        if not node.source:
            return False

        value = get_value(node.source)
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return False

        try:
            numeric_value = float(value)
        except Exception:
            return False

        return self._evaluate_operator_comparison(
            operator=node.operator,
            value=numeric_value,
            threshold=node.threshold,
            min_value=node.min,
            max_value=node.max,
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

        return self._evaluate_operator_comparison(
            operator=node.operator,
            value=diff,
            threshold=node.threshold,
            min_value=node.min,
            max_value=node.max,
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
        """Compare a value based on the operator; EQUAL supports optional epsilon."""
        if operator == ConditionOperator.GREATER_THAN:
            return threshold is not None and value > threshold

        if operator == ConditionOperator.LESS_THAN:
            return threshold is not None and value < threshold

        if operator == ConditionOperator.EQUAL:
            if threshold is None:
                return False
            if self.comparison_tolerance is None:
                return value == threshold
            return abs(value - threshold) <= self.comparison_tolerance

        if operator == ConditionOperator.BETWEEN:
            return (min_value is not None) and (max_value is not None) and (min_value <= value <= max_value)

        return False
