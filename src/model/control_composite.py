from __future__ import annotations

import logging

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

    # Group (branch)
    all: list[CompositeNode] | None = None
    any: list[CompositeNode] | None = None
    not_: CompositeNode | list[CompositeNode] | None = Field(default=None, alias="not")

    # Leaf (leaf node)
    type: ConditionType | None = None
    operator: ConditionOperator | None = None
    hysteresis: float | None = None
    debounce_sec: float | None = None

    # threshold
    source: str | None = None
    threshold: float | None = None
    min: float | None = None
    max: float | None = None

    # difference
    sources: list[str] | None = None
    abs: bool | None = True

    invalid: bool = False

    @model_validator(mode="after")
    def _validate_structure(self) -> CompositeNode:
        problems: list[str] = []
        group_count = sum(x is not None for x in (self.all, self.any, self.not_))
        is_leaf = self.type is not None

        # group exactly one OR leaf exactly one
        if group_count == 1 and not is_leaf:
            if self.all is not None and not self.all:
                problems.append("'all' must contain at least one child")
            if self.any is not None and not self.any:
                problems.append("'any' must contain at least one child")
            if self.not_ is not None and isinstance(self.not_, list):
                problems.append("'not' must be a single CompositeNode")

        elif group_count == 0 and is_leaf:
            if self.type == ConditionType.THRESHOLD:
                if self.operator is None:
                    problems.append("threshold leaf requires 'operator'")
                elif self.operator == ConditionOperator.BETWEEN:
                    if self.min is None or self.max is None:
                        problems.append("threshold-between requires 'min' and 'max'")
                else:
                    if self.threshold is None:
                        problems.append("threshold leaf requires 'threshold' when operator is not 'between'")
                if not self.source:
                    problems.append("threshold leaf requires non-empty 'source'")

            elif self.type == ConditionType.DIFFERENCE:
                if self.operator is None:
                    problems.append("difference leaf requires 'operator'")
                if not self.sources or len(self.sources) != 2:
                    problems.append("difference leaf requires 'sources' of length 2")
            else:
                problems.append(f"unsupported leaf type: {self.type}")

        else:
            problems.append("must be group(all/any/not) OR leaf(type=threshold|difference)")

        if problems:
            for msg in problems:
                logger.warning(f"[CONFIG] Composite invalid: {msg}")
            object.__setattr__(self, "invalid", True)

        return self

    @field_validator("sources", mode="before")
    @classmethod
    def _normalize_sources(cls, v):
        if v is None:
            return None
        try:
            return [s for s in (str(x).strip() for x in v) if s]
        except Exception:
            return None
