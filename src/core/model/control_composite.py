from __future__ import annotations

import logging
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.model.enum.condition_enum import ConditionOperator, ConditionType

logger = logging.getLogger(__name__)


class CompositeNode(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        use_enum_values=False,
        validate_assignment=True,
        populate_by_name=True,
    )

    # Class constants (use ClassVar to exclude from core.model fields)
    MAX_NESTING_DEPTH: ClassVar[int] = 10
    MAX_CHILDREN_PER_NODE: ClassVar[int] = 20

    # Group (branch) - logical operators
    all: list[CompositeNode] | None = None
    any: list[CompositeNode] | None = None
    not_: CompositeNode | None = Field(default=None, alias="not")

    # Leaf (leaf node) - condition types
    type: ConditionType | None = None
    operator: ConditionOperator | None = None
    hysteresis: float | None = None
    debounce_sec: float | None = None

    # threshold condition fields
    threshold: float | None = None
    min: float | None = None
    max: float | None = None

    # difference condition fields
    sources: list[str] | None = None
    abs: bool | None = Field(default=False)

    # time_elapsed condition fields
    interval_hours: float | None = None

    # validation state
    invalid: bool = False

    def calculate_max_depth(self, visited: set[int] | None = None) -> int:
        """
        Calculate maximum nesting depth of the composite tree.
        Also detects circular references.

        Args:
            visited: Set of object IDs to track visited nodes for cycle detection

        Returns:
            Maximum depth of nested structure, or -1 if circular reference detected
        """
        if visited is None:
            visited = set()

        # Circular reference detection - return -1 instead of raising exception
        node_id = id(self)
        if node_id in visited:
            logger.error("[COMPOSITE] Circular reference detected in composite structure")
            return -1

        visited.add(node_id)
        max_child_depth = 0

        try:
            # Check all child nodes
            child_nodes = []
            if self.all:
                child_nodes.extend(self.all)
            if self.any:
                child_nodes.extend(self.any)
            if self.not_:
                child_nodes.append(self.not_)

            # Calculate depth of each child
            for child in child_nodes:
                child_depth = child.calculate_max_depth(visited.copy())
                if child_depth == -1:  # Circular reference in child
                    return -1
                max_child_depth = max(max_child_depth, child_depth)

        finally:
            visited.remove(node_id)

        return max_child_depth + 1

    @model_validator(mode="after")
    def validate_structure(self) -> CompositeNode:
        problems: list[str] = []

        group_count = sum(x is not None for x in (self.all, self.any, self.not_))
        is_leaf = self.type is not None

        # ---- Basic structure: group vs leaf ----
        match (group_count, is_leaf):
            # Group node: exactly 1 of (all / any / not_) is set, and no type
            case (1, False):
                problems.extend(self._validate_group_node())

            # Leaf node: no group, but has type
            case (0, True):
                problems.extend(self._validate_leaf_node())

            # Anything else is invalid
            case _:
                problems.append(
                    "node must be either group(all/any/not) OR "
                    "leaf(type=threshold|difference|average|sum|min|max|time_elapsed)"
                )

        # ---- Advanced validations (only if basic structure is valid) ----
        if not problems:
            depth = self.calculate_max_depth()
            if depth == -1:
                problems.append("circular reference detected in composite structure")
            elif depth > self.MAX_NESTING_DEPTH:
                problems.append(f"composite structure exceeds maximum nesting depth " f"({self.MAX_NESTING_DEPTH})")

        # ---- Mark invalid & log ----
        if problems:
            for msg in problems:
                logger.warning(f"[COMPOSITE] Validation error: {msg}")
            object.__setattr__(self, "invalid", True)

        return self

    @field_validator("sources", mode="before")
    @classmethod
    def normalize_sources(cls, v):
        """Normalize and validate sources list"""
        if v is None:
            return None
        try:
            if isinstance(v, str):
                stripped: str = v.strip()
                return [stripped] if stripped else None

            if not isinstance(v, (list, tuple, set)):
                logger.warning(f"[COMPOSITE] sources should be a list or string, got {type(v).__name__}: {v}")
                return None

            normalized: list[str] = [s for s in (str(x).strip() for x in v) if s]
            return normalized or None
        except (TypeError, AttributeError) as e:
            logger.warning(f"[COMPOSITE] Failed to normalize sources {v}: {e}")
            return None

    @field_validator("hysteresis", "debounce_sec", "threshold", "min", "max", "interval_hours")  # ← MODIFIED
    @classmethod
    def validate_numeric_fields(cls, v, info):
        """Ensure numeric fields are non-negative where applicable"""
        if v is not None:
            try:
                float_v = float(v)
                if float_v < 0:
                    field_name = info.field_name if hasattr(info, "field_name") else "numeric_field"
                    logger.warning(f"[COMPOSITE] {field_name} should be non-negative, got: {float_v}")
                return float_v
            except (ValueError, TypeError):
                field_name = info.field_name if hasattr(info, "field_name") else "numeric_field"
                logger.error(f"[COMPOSITE] Invalid numeric value for {field_name}: {v}")
                return None
        return v

    def _validate_operator_threshold_combination(self) -> list[str]:
        """Validate operator and threshold field combinations for leaf nodes"""
        problems = []

        if self.type != ConditionType.THRESHOLD:
            return problems

        operator: ConditionOperator | None = self.operator

        match operator:
            # ------------------------------
            # BETWEEN
            # ------------------------------
            case ConditionOperator.BETWEEN:
                if self.min is None or self.max is None:
                    problems.append("BETWEEN operator requires both 'min' and 'max' values")
                elif self.min >= self.max:
                    problems.append("For BETWEEN operator, 'min' must be less than 'max'")

                if self.threshold is not None:
                    problems.append("BETWEEN operator should not specify 'threshold' (use 'min' and 'max')")

            # ------------------------------
            # EQUAL
            # ------------------------------
            case ConditionOperator.EQUAL:
                if self.threshold is None:
                    problems.append("EQUAL operator requires 'threshold' value")

                if self.min is not None or self.max is not None:
                    problems.append("EQUAL operator should not specify 'min' or 'max' (use 'threshold')")

            # ------------------------------
            # GREATER / LESS variants
            # ------------------------------
            case (
                ConditionOperator.GREATER_THAN
                | ConditionOperator.LESS_THAN
                | ConditionOperator.GREATER_THAN_OR_EQUAL
                | ConditionOperator.LESS_THAN_OR_EQUAL
            ):
                if self.threshold is None:
                    problems.append(f"{operator.value.upper()} operator requires 'threshold' value")

                if self.min is not None or self.max is not None:
                    problems.append(
                        f"{operator.value.upper()} operator should not specify 'min' or 'max' (use 'threshold')"
                    )

            # ------------------------------
            # Default: no additional validation
            # ------------------------------
            case _:
                pass

        return problems

    # ====== Group node helpers ======

    def _validate_group_node(self) -> list[str]:
        """Validate group node (all / any / not_)"""
        problems: list[str] = []

        problems.extend(self._validate_group_children("all", self.all))
        problems.extend(self._validate_group_children("any", self.any))

        # not_ is a single child
        if self.not_ is not None and self.not_.invalid:
            problems.append("'not' contains invalid child node")

        return problems

    def _validate_group_children(
        self,
        group_name: str,
        children: list["CompositeNode"] | None,
    ) -> list[str]:
        """Shared validation logic for 'all' and 'any' groups."""
        problems: list[str] = []

        if children is None:
            return problems

        if not children:
            problems.append(f"'{group_name}' must contain at least one child")
        elif len(children) > self.MAX_CHILDREN_PER_NODE:
            problems.append(f"'{group_name}' cannot have more than {self.MAX_CHILDREN_PER_NODE} children")

        # Always check child validity regardless of count issues
        if children:
            invalid_indices = [i for i, child in enumerate(children) if child.invalid]
            if invalid_indices:
                problems.append(f"'{group_name}' contains invalid child nodes at indices: {invalid_indices}")

        return problems

    # ====== Leaf node dispatcher (match-case by type) ======

    def _validate_leaf_node(self) -> list[str]:
        """Dispatch leaf validation based on condition type."""
        problems: list[str] = []

        if self.type is None:
            problems.append("leaf node must have 'type'")
            return problems

        match self.type:
            case ConditionType.THRESHOLD:
                problems.extend(self._validate_threshold_leaf())

            case ConditionType.DIFFERENCE:
                problems.extend(self._validate_difference_leaf())

            case ConditionType.AVERAGE | ConditionType.SUM | ConditionType.MIN | ConditionType.MAX:
                problems.extend(self._validate_aggregate_leaf())

            case ConditionType.TIME_ELAPSED:
                problems.extend(self._validate_time_elapsed_leaf())

            case _:
                problems.append(f"unsupported condition type: {self.type}")

        return problems

    # ====== THRESHOLD leaf ======

    def _validate_threshold_leaf(self) -> list[str]:
        problems: list[str] = []

        if not self.sources:
            problems.append("threshold condition requires non-empty 'sources' list")
            return problems

        if len(self.sources) != 1:
            problems.append("threshold condition requires exactly 1 source in 'sources' list")
            return problems

        problems.extend(self._validate_operator_threshold_combination())
        return problems

    # ====== DIFFERENCE leaf ======

    def _validate_difference_leaf(self) -> list[str]:
        problems: list[str] = []

        # operator
        if self.operator is None:
            problems.append("difference condition requires 'operator'")

        # sources
        if not self.sources:
            problems.append("difference condition requires 'sources' list")
        elif len(self.sources) != 2:
            problems.append("difference condition requires exactly 2 sources")
        elif self.sources[0] == self.sources[1]:
            problems.append("difference condition sources must be different")

        # operator compatibility (using match-case)
        match self.operator:
            case ConditionOperator.BETWEEN:
                if self.min is None or self.max is None:
                    problems.append("difference-BETWEEN requires 'min' and 'max' values")

            case ConditionOperator.GREATER_THAN | ConditionOperator.LESS_THAN | ConditionOperator.EQUAL:
                if self.threshold is None:
                    problems.append(f"difference-{self.operator.value.upper()} requires 'threshold' value")

            case _:
                # other operators are either unsupported or don't need extra validation
                pass

        return problems

    # ====== AVERAGE / SUM / MIN / MAX leaf ======

    def _validate_aggregate_leaf(self) -> list[str]:
        """Validation for AVERAGE / SUM / MIN / MAX types."""
        problems: list[str] = []
        agg_type = self.type.value if self.type is not None else "aggregate"  # just for shorter messages

        # operator
        if self.operator is None:
            problems.append(f"{agg_type} condition requires 'operator'")

        # sources: at least 2, all unique
        if not self.sources:
            problems.append(f"{agg_type} condition requires 'sources' list")
        elif len(self.sources) < 2:
            problems.append(f"{agg_type} condition requires at least 2 sources")
        elif len(set(self.sources)) != len(self.sources):
            problems.append(f"{agg_type} condition sources must be unique (found duplicates)")

        # operator compatibility (using match-case)
        match self.operator:
            case ConditionOperator.BETWEEN:
                if self.min is None or self.max is None:
                    problems.append(f"{agg_type}-BETWEEN requires 'min' and 'max' values")

            case (
                ConditionOperator.GREATER_THAN
                | ConditionOperator.LESS_THAN
                | ConditionOperator.EQUAL
                | ConditionOperator.GREATER_THAN_OR_EQUAL
                | ConditionOperator.LESS_THAN_OR_EQUAL
            ):
                if self.threshold is None:
                    problems.append(f"{agg_type}-{self.operator.value.upper()} requires 'threshold' value")

            case _:
                # other operators either unsupported or don't have extra constraints here
                pass

        return problems

    # ====== TIME_ELAPSED leaf ======

    def _validate_time_elapsed_leaf(self) -> list[str]:
        """Validation for TIME_ELAPSED type."""
        problems: list[str] = []

        # Must have interval_hours
        if self.interval_hours is None:
            problems.append("time_elapsed condition requires 'interval_hours'")
        elif self.interval_hours <= 0:
            problems.append("time_elapsed 'interval_hours' must be positive")

        # time_elapsed doesn't need these fields
        if self.operator is not None:
            problems.append("time_elapsed condition should not specify 'operator'")
        if self.sources is not None:
            problems.append("time_elapsed condition should not specify 'sources'")
        if self.threshold is not None:
            problems.append("time_elapsed condition should not specify 'threshold'")
        if self.min is not None or self.max is not None:
            problems.append("time_elapsed condition should not specify 'min' or 'max'")

        return problems
