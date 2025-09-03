from logging import Logger


class ConstraintPolicy:
    def __init__(self, constraints: dict | None, logger: Logger):
        self.constraints = constraints or {}
        self.logger = logger

    def allow(self, name: str, value: float) -> bool:
        constraint_limit: dict = self.constraints.get(name)
        if not constraint_limit:
            return True
        min_limit: int = constraint_limit.get("min", float("-inf"))
        max_limit: int = constraint_limit.get("max", float("inf"))
        is_ok: bool = min_limit <= value <= max_limit
        if not is_ok:
            self.logger.warning(f"Reject write: {name}={value} out of range [{min_limit}, {max_limit}]")
        return is_ok
