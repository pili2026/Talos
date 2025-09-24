from __future__ import annotations

import logging
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from model.enum.condition_enum import ConditionOperator, ConditionType

logger = logging.getLogger(__name__)


class CompositeNode(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        use_enum_values=False,
        validate_assignment=True,
        populate_by_name=True,
    )

    # Class constants (use ClassVar to exclude from model fields)
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
    source: str | None = None
    threshold: float | None = None
    min: float | None = None
    max: float | None = None

    # difference condition fields
    sources: list[str] | None = None
    abs: bool | None = True

    # validation state
    invalid: bool = False

    def calculate_max_depth(self, visited: set[id] = None) -> int:
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

    def _validate_operator_threshold_combination(self) -> list[str]:
        """Validate operator and threshold field combinations for leaf nodes"""
        problems = []

        if self.type != ConditionType.THRESHOLD:
            return problems

        if self.operator == ConditionOperator.BETWEEN:
            # BETWEEN requires both min and max
            if self.min is None or self.max is None:
                problems.append("BETWEEN operator requires both 'min' and 'max' values")
            elif self.min >= self.max:
                problems.append("For BETWEEN operator, 'min' must be less than 'max'")
            # BETWEEN should not use threshold
            if self.threshold is not None:
                problems.append("BETWEEN operator should not specify 'threshold' (use 'min' and 'max')")

        elif self.operator == ConditionOperator.EQUAL:
            # EQUAL requires threshold
            if self.threshold is None:
                problems.append("EQUAL operator requires 'threshold' value")
            # EQUAL should not use min/max
            if self.min is not None or self.max is not None:
                problems.append("EQUAL operator should not specify 'min' or 'max' (use 'threshold')")

        elif self.operator in {ConditionOperator.GREATER_THAN, ConditionOperator.LESS_THAN}:
            # GT/LT requires threshold
            if self.threshold is None:
                problems.append(f"{self.operator.value.upper()} operator requires 'threshold' value")
            # GT/LT should not use min/max
            if self.min is not None or self.max is not None:
                problems.append(
                    f"{self.operator.value.upper()} operator should not specify 'min' or 'max' (use 'threshold')"
                )

        return problems

    @model_validator(mode="after")
    def validate_structure(self) -> CompositeNode:
        problems: list[str] = []
        group_count = sum(x is not None for x in (self.all, self.any, self.not_))
        is_leaf = self.type is not None

        # Basic structure validation: exactly one group OR exactly one leaf
        if group_count == 1 and not is_leaf:
            # Group node validation
            if self.all is not None:
                if not self.all:
                    problems.append("'all' must contain at least one child")
                elif len(self.all) > self.MAX_CHILDREN_PER_NODE:
                    problems.append(f"'all' cannot have more than {self.MAX_CHILDREN_PER_NODE} children")

                # Always check child validity regardless of count issues
                if self.all:
                    invalid_children = [i for i, child in enumerate(self.all) if child.invalid]
                    if invalid_children:
                        problems.append(f"'all' contains invalid child nodes at indices: {invalid_children}")

            if self.any is not None:
                if not self.any:
                    problems.append("'any' must contain at least one child")
                elif len(self.any) > self.MAX_CHILDREN_PER_NODE:
                    problems.append(f"'any' cannot have more than {self.MAX_CHILDREN_PER_NODE} children")

                # Always check child validity regardless of count issues
                if self.any:
                    invalid_children = [i for i, child in enumerate(self.any) if child.invalid]
                    if invalid_children:
                        problems.append(f"'any' contains invalid child nodes at indices: {invalid_children}")

            if self.not_ is not None:
                # Check if the 'not' child node is invalid
                if self.not_.invalid:
                    problems.append("'not' contains invalid child node")

        elif group_count == 0 and is_leaf:
            # Leaf node validation
            if self.type == ConditionType.THRESHOLD:
                if self.operator is None:
                    problems.append("threshold condition requires 'operator'")
                else:
                    # Advanced operator-threshold combination validation
                    problems.extend(self._validate_operator_threshold_combination())

                if not self.source:
                    problems.append("threshold condition requires non-empty 'source'")

            elif self.type == ConditionType.DIFFERENCE:
                if self.operator is None:
                    problems.append("difference condition requires 'operator'")

                # Validate sources list with clear error messages
                if not self.sources:
                    problems.append("difference condition requires 'sources' list")
                elif len(self.sources) != 2:
                    problems.append("difference condition requires exactly 2 sources")
                elif self.sources[0] == self.sources[1]:
                    problems.append("difference condition sources must be different")

                # Validate operator compatibility with difference type
                if self.operator == ConditionOperator.BETWEEN:
                    if self.min is None or self.max is None:
                        problems.append("difference-BETWEEN requires 'min' and 'max' values")
                elif self.operator in {
                    ConditionOperator.GREATER_THAN,
                    ConditionOperator.LESS_THAN,
                    ConditionOperator.EQUAL,
                }:
                    if self.threshold is None:
                        problems.append(f"difference-{self.operator.value.upper()} requires 'threshold' value")
            else:
                problems.append(f"unsupported condition type: {self.type}")
        else:
            problems.append("node must be either group(all/any/not) OR leaf(type=threshold|difference)")

        # Advanced validations (only if basic structure is valid)
        if not problems:
            # Check nesting depth and circular references - no exceptions, just validation
            depth = self.calculate_max_depth()
            if depth == -1:
                problems.append("circular reference detected in composite structure")
            elif depth > self.MAX_NESTING_DEPTH:
                problems.append(f"composite structure exceeds maximum nesting depth ({self.MAX_NESTING_DEPTH})")

        # Log problems and mark as invalid if any found
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
            normalized = [s for s in (str(x).strip() for x in v) if s]
            return normalized if normalized else None
        except (TypeError, AttributeError) as e:
            logger.warning(f"[COMPOSITE] Failed to normalize sources {v}: {e}")
            return None

    @field_validator("hysteresis", "debounce_sec", "threshold", "min", "max")
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
            except (ValueError, TypeError) as e:
                field_name = info.field_name if hasattr(info, "field_name") else "numeric_field"
                logger.error(f"[COMPOSITE] Invalid numeric value for {field_name}: {v}")
                return None
        return v
