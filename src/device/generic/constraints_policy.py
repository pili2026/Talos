from logging import Logger

from schema.constraint_schema import ConstraintConfig


class ConstraintPolicy:
    def __init__(self, constraints: dict[str, ConstraintConfig] | None, logger: Logger):
        self.constraints = constraints or {}
        self.logger = logger

    def allow(self, name: str, value: float) -> bool:
        constraint: ConstraintConfig = self.constraints.get(name)
        if not constraint:
            return True

        min_limit = constraint.min if constraint.min is not None else float("-inf")
        max_limit = constraint.max if constraint.max is not None else float("inf")

        is_ok: bool = min_limit <= value <= max_limit
        if not is_ok:
            self.logger.warning(f"Reject write: {name}={value} out of range [{min_limit}, {max_limit}]")
        return is_ok
