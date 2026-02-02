from __future__ import annotations

import logging
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.model.enum.condition_enum import AggregationType, ConditionOperator, ConditionType
from core.schema.control_condition_source_schema import Source

logger = logging.getLogger(__name__)


class CompositeNode(BaseModel):
    """
    Composite condition tree node (v2.0).
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        use_enum_values=False,
        validate_assignment=True,
        populate_by_name=True,
    )

    sources_id: str | None = Field(
        default=None,
        description=(
            "Condition identifier. Required when policy needs to reference "
            "this condition (e.g., for absolute_linear or incremental_linear)."
        ),
    )

    # Class constants
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

    # threshold / numeric fields
    threshold: float | None = None
    min: float | None = None
    max: float | None = None

    sources: list[Source] | None = None

    abs: bool | None = Field(default=False)

    # time_elapsed condition fields
    interval_hours: float | None = None

    # validation state
    invalid: bool = False

    # =========================
    # Tree utilities
    # =========================

    def calculate_max_depth(self, visited: set[int] | None = None) -> int:
        """Calculate maximum nesting depth of the composite tree."""
        if visited is None:
            visited = set()

        node_id = id(self)
        if node_id in visited:
            logger.error("[COMPOSITE] Circular reference detected in composite structure")
            return -1

        visited.add(node_id)
        max_child_depth = 0

        try:
            child_nodes: list[CompositeNode] = []
            if self.all:
                child_nodes.extend(self.all)
            if self.any:
                child_nodes.extend(self.any)
            if self.not_:
                child_nodes.append(self.not_)

            for child in child_nodes:
                child_depth = child.calculate_max_depth(visited.copy())
                if child_depth == -1:
                    return -1
                max_child_depth = max(max_child_depth, child_depth)

        finally:
            visited.remove(node_id)

        return max_child_depth + 1

    # =========================
    # Root validator
    # =========================

    @model_validator(mode="after")
    def validate_structure(self) -> CompositeNode:
        """Validate composite structure."""
        problems: list[str] = []

        group_count = sum(x is not None for x in (self.all, self.any, self.not_))
        is_leaf = self.type is not None

        match (group_count, is_leaf):
            case (1, False):
                problems.extend(self._validate_group_node())
            case (0, True):
                problems.extend(self._validate_leaf_node())
            case _:
                problems.append(
                    "node must be either group(all/any/not) OR "
                    "leaf(type=threshold|difference|average|sum|min|max|time_elapsed)"
                )

        if not problems:
            depth = self.calculate_max_depth()
            if depth == -1:
                problems.append("circular reference detected in composite structure")
            elif depth > self.MAX_NESTING_DEPTH:
                problems.append(f"composite structure exceeds maximum nesting depth ({self.MAX_NESTING_DEPTH})")

        if problems:
            for msg in problems:
                logger.warning(f"[COMPOSITE] Validation error: {msg}")
            raise ValueError("; ".join(problems))

        return self

    # =========================
    # Field validators
    # =========================

    @field_validator("hysteresis", "debounce_sec", "threshold", "min", "max", "interval_hours")
    @classmethod
    def validate_numeric_fields(cls, v, info):
        """Ensure numeric fields are non-negative where applicable."""
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

    # =========================
    # Helpers (signatures / identity)
    # =========================

    def _build_input_signature(self, source: Source, pin: str) -> tuple[str, str, str, str | None]:
        """
        Build a unique identity for a single input pin.
        Used to detect duplicated inputs in difference conditions.
        """
        aggregation = source.get_effective_aggregation()
        aggregation_value = aggregation.value if aggregation else None
        return (source.device, str(source.slave_id), pin, aggregation_value)

    def _expand_sources_to_input_signatures(self, sources: list[Source]) -> list[tuple[str, str, str, str | None]]:
        """Expand sources into per-pin input signatures."""
        signatures: list[tuple[str, str, str, str | None]] = []
        for source in sources:
            for pin in source.pins:
                signatures.append(self._build_input_signature(source, pin))
        return signatures

    def _build_source_signature(self, source: Source) -> tuple[str, str, tuple[str, ...], str | None]:
        """
        Build a unique identity for a Source (device/slave + pins + aggregation).
        Used to detect duplicated sources in aggregate conditions.
        """
        aggregation = source.get_effective_aggregation()
        aggregation_value = aggregation.value if aggregation else None
        return (source.device, str(source.slave_id), tuple(source.pins), aggregation_value)

    # =========================
    # Operator + threshold rules (THRESHOLD only)
    # =========================

    def _validate_operator_threshold_combination(self) -> list[str]:
        problems: list[str] = []

        if self.type != ConditionType.THRESHOLD:
            return problems

        operator: ConditionOperator | None = self.operator

        match operator:
            case ConditionOperator.BETWEEN:
                if self.min is None or self.max is None:
                    problems.append("BETWEEN operator requires both 'min' and 'max' values")
                elif self.min >= self.max:
                    problems.append("For BETWEEN operator, 'min' must be less than 'max'")
                if self.threshold is not None:
                    problems.append("BETWEEN operator should not specify 'threshold' (use 'min' and 'max')")

            case ConditionOperator.EQUAL:
                if self.threshold is None:
                    problems.append("EQUAL operator requires 'threshold' value")
                if self.min is not None or self.max is not None:
                    problems.append("EQUAL operator should not specify 'min' or 'max' (use 'threshold')")

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

            case ConditionOperator.NOT_EQUAL:
                if self.threshold is None:
                    problems.append("NOT_EQUAL operator requires 'threshold' value")
                if self.min is not None or self.max is not None:
                    problems.append("NOT_EQUAL operator should not specify 'min' or 'max' (use 'threshold')")

            case _:
                if operator is not None:
                    logger.warning(f"Operator '{operator.value}' is not supported")

        return problems

    # =========================
    # Group nodes
    # =========================

    def _validate_group_node(self) -> list[str]:
        problems: list[str] = []
        problems.extend(self._validate_group_children("all", self.all))
        problems.extend(self._validate_group_children("any", self.any))

        if self.not_ is not None and self.not_.invalid:
            problems.append("'not' contains invalid child node")

        return problems

    def _validate_group_children(self, group_name: str, children: list[CompositeNode] | None) -> list[str]:
        problems: list[str] = []

        if children is None:
            return problems

        if not children:
            problems.append(f"'{group_name}' must contain at least one child")
        elif len(children) > self.MAX_CHILDREN_PER_NODE:
            problems.append(f"'{group_name}' cannot have more than {self.MAX_CHILDREN_PER_NODE} children")

        if children:
            invalid_indices = [i for i, child in enumerate(children) if child.invalid]
            if invalid_indices:
                problems.append(f"'{group_name}' contains invalid child nodes at indices: {invalid_indices}")

        return problems

    # =========================
    # Leaf dispatcher
    # =========================

    def _validate_leaf_node(self) -> list[str]:
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

    # =========================
    # THRESHOLD leaf
    # =========================

    def _validate_threshold_leaf(self) -> list[str]:
        problems: list[str] = []

        if not self.sources:
            problems.append("threshold condition requires non-empty 'sources' list")
            return problems

        # Type check
        for idx, source in enumerate(self.sources):
            if not isinstance(source, Source):
                problems.append(f"threshold source[{idx}] must be Source object, got {type(source).__name__}")
                return problems

        total_pins: int = sum(len(source.pins) for source in self.sources)

        # Case A) single scalar input (total pins == 1)
        if total_pins == 1:
            problems.extend(self._validate_operator_threshold_combination())
            return problems

        # Case B) multi-pin threshold is ONLY allowed for SINGLE source with intra-source aggregation
        if len(self.sources) != 1:
            problems.append(
                "threshold with multiple pins is only allowed for a single source with intra-source aggregation; "
                f"got {len(self.sources)} sources and {total_pins} pins"
            )
            return problems

        source = self.sources[0]
        agg = source.get_effective_aggregation()
        if agg is None:
            problems.append(
                f"threshold with multiple pins requires aggregation to reduce to a scalar; got pins={source.pins}"
            )
            return problems

        # Multi-pin threshold with aggregation is valid; still must validate operator/threshold fields
        problems.extend(self._validate_operator_threshold_combination())
        return problems

    # =========================
    # DIFFERENCE leaf
    # =========================

    def _validate_difference_leaf(self) -> list[str]:
        problems: list[str] = []

        if self.operator is None:
            problems.append("difference condition requires 'operator'")

        if not self.sources:
            problems.append("difference condition requires 'sources' list")
            return problems

        # Type check
        for idx, source in enumerate(self.sources):
            if not isinstance(source, Source):
                problems.append(f"difference source[{idx}] must be Source object, got {type(source).__name__}")
                return problems

        effective_inputs: list[tuple[str, str, str, str | None]] = []

        for source in self.sources:
            if not source.pins:
                problems.append("difference condition source pins cannot be empty")
                return problems

            aggregation: AggregationType | None = source.get_effective_aggregation()
            aggregation_value = aggregation.value if aggregation else None

            # Multiple pins with aggregation → collapses to 1 effective input
            if len(source.pins) > 1 and aggregation is not None:
                pins_key = ",".join(sorted(source.pins))
                effective_inputs.append(
                    (source.device, str(source.slave_id), f"aggregation({pins_key})", aggregation_value)
                )
                continue

            # Raw pins (no aggregation) → each pin is an effective input
            for pin in source.pins:
                effective_inputs.append((source.device, str(source.slave_id), pin, aggregation_value))

        # DIFFERENCE requires exactly 2 effective inputs
        if len(effective_inputs) != 2:
            problems.append(
                f"difference condition requires exactly 2 effective inputs after aggregation, "
                f"got {len(effective_inputs)} input(s). "
                f"Hint: Use intra-source aggregation to reduce multiple pins to one value per source. "
                f"Details: {effective_inputs}"
            )
            return problems

        # Must be two DISTINCT inputs
        if effective_inputs[0] == effective_inputs[1]:
            problems.append(f"difference condition requires two distinct inputs; " f"duplicate: {effective_inputs[0]}")
            return problems

        # Operator/threshold validation
        match self.operator:
            case ConditionOperator.BETWEEN:
                if self.min is None or self.max is None:
                    problems.append("difference-BETWEEN requires 'min' and 'max' values")
            case (
                ConditionOperator.GREATER_THAN
                | ConditionOperator.LESS_THAN
                | ConditionOperator.EQUAL
                | ConditionOperator.GREATER_THAN_OR_EQUAL
                | ConditionOperator.LESS_THAN_OR_EQUAL
                | ConditionOperator.NOT_EQUAL
            ):
                if self.threshold is None:
                    problems.append(f"difference-{self.operator.value.upper()} requires 'threshold' value")
            case _:
                pass

        return problems

    # =========================
    # Aggregate leaf: AVERAGE / SUM / MIN / MAX
    # =========================

    def _validate_aggregate_leaf(self) -> list[str]:
        problems: list[str] = []
        agg_type = self.type.value if self.type is not None else "aggregate"

        if self.operator is None:
            problems.append(f"{agg_type} condition requires 'operator'")

        if not self.sources:
            problems.append(f"{agg_type} condition requires 'sources' list")
            return problems

        if len(self.sources) < 2:
            problems.append(
                f"{agg_type} condition requires at least 2 sources for aggregation, "
                f"got {len(self.sources)} source(s). "
                f"Note: Each source produces one value (after intra-source aggregation if applicable). "
                f"For single source with multiple pins, use 'threshold' with intra-source aggregation instead."
            )
            return problems

        # Type check
        for idx, source in enumerate(self.sources):
            if not isinstance(source, Source):
                problems.append(f"{agg_type} source[{idx}] must be Source object, got {type(source).__name__}")

        if problems:
            return problems

        # Duplicate source detection
        sigs = [self._build_source_signature(s) for s in self.sources]
        if len(sigs) != len(set(sigs)):
            dup_sigs = {sig for sig in sigs if sigs.count(sig) > 1}
            problems.append(f"{agg_type} condition sources must be distinct; duplicates: {dup_sigs}")

        # Operator validation
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
                | ConditionOperator.NOT_EQUAL
            ):
                if self.threshold is None:
                    problems.append(f"{agg_type}-{self.operator.value.upper()} requires 'threshold' value")
            case _:
                pass

        return problems

    # =========================
    # TIME_ELAPSED leaf
    # =========================

    def _validate_time_elapsed_leaf(self) -> list[str]:
        problems: list[str] = []

        if self.interval_hours is None:
            problems.append("time_elapsed condition requires 'interval_hours'")
        elif self.interval_hours <= 0:
            problems.append("time_elapsed 'interval_hours' must be positive")

        if self.operator is not None:
            problems.append("time_elapsed condition should not specify 'operator'")
        if self.sources is not None:
            problems.append("time_elapsed condition should not specify 'sources'")
        if self.threshold is not None:
            problems.append("time_elapsed condition should not specify 'threshold'")
        if self.min is not None or self.max is not None:
            problems.append("time_elapsed condition should not specify 'min' or 'max'")

        return problems
