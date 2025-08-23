import logging
from functools import partial
from typing import Optional

from control_config import ControlConfig
from evaluator.composite_evaluator import CompositeEvaluator
from model.control_composite import CompositeNode
from model.control_model import ControlActionModel, ControlConditionModel

logger = logging.getLogger(__name__)


class ControlEvaluator:
    """
    Responsibilities:
    - Retrieve the control rule list for the specified (model, slave_id)
    - Evaluate each rule and select the one that matches with the highest priority
    - Return the corresponding Action (at most one)
    """

    def __init__(self, control_config: ControlConfig):
        self.control_config = control_config
        self.composite_evaluator = CompositeEvaluator()

    # Centralized snapshot access (easy to refactor later)
    def get_snapshot_value(self, snapshot: dict[str, float], key: str) -> Optional[float]:
        """
        Fetch a numeric value by key from the given snapshot.
        If your snapshot structure changes (namespacing, nesting, etc.),
        just update this method.
        """
        return snapshot.get(key)

    def evaluate(self, model: str, slave_id: str, snapshot: dict[str, float]) -> list[ControlActionModel]:
        conditions = self.control_config.get_control_list(model, slave_id)

        best_condition: ControlConditionModel | None = None
        best_priority: int | None = None

        # Pre-bind snapshot so the callback fits Callable[[str], Optional[float]]
        get_value = partial(self.get_snapshot_value, snapshot)

        for condition_model in conditions:
            composite: CompositeNode = getattr(condition_model, "composite", None)
            if composite is None or getattr(composite, "invalid", False):
                continue

            is_matched: bool = self.composite_evaluator.evaluate_composite_node(composite, get_value)
            if not is_matched:
                continue

            # Keep only the highest priority; if equal, keep the first encountered
            if best_condition is None:
                best_condition = condition_model
                best_priority = condition_model.priority
            else:
                if best_priority is None or condition_model.priority > best_priority:
                    best_condition = condition_model
                    best_priority = condition_model.priority

        if best_condition is None:
            return []

        selected = best_condition
        action: ControlActionModel = selected.action

        missing_field_list = []
        if not action.model:
            missing_field_list.append("model")
        if not action.slave_id:
            missing_field_list.append("slave_id")

        if missing_field_list:
            logger.warning(
                f"[EVAL] Skip rule '{selected.code}' (p={selected.priority}) "
                f"due to missing action fields: {', '.join(missing_field_list)}"
            )
            return []

        # Concise reason (composite summary)
        try:
            comp_summary = (
                self.composite_evaluator.build_composite_reason_summary(selected.composite)
                if selected.composite
                else "composite"
            )
        except Exception:
            comp_summary = "composite"

        action.reason = f"[{selected.code}] {selected.name} | {comp_summary} | priority={selected.priority}"

        logger.info(
            f"[EVAL] Pick '{selected.code}' (p={selected.priority}) " f"model={model} slave_id={slave_id} via composite"
        )
        return [action]
