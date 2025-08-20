from control_config import ControlConfig
from model.control_model import ControlActionModel, ControlConditionModel
from model.enum.condition_enum import ConditionOperator, ConditionType


class ControlEvaluator:
    def __init__(self, control_config: ControlConfig):
        self.control_config = control_config

    def evaluate(self, model: str, slave_id: str, snapshot: dict[str, float]) -> list[ControlActionModel]:
        conditions = self.control_config.get_control_list(model, slave_id)

        best_condition: ControlConditionModel | None = None
        best_priority: int | None = None

        for cond in conditions:
            if not self._check_condition(cond, snapshot):
                continue

            if best_condition is None or cond.priority > best_priority:
                best_condition = cond
                best_priority = cond.priority

        return [best_condition.action] if best_condition else []

    def _check_condition(self, condition: ControlConditionModel, snapshot: dict[str, float]) -> bool:
        if condition.type == ConditionType.DIFFERENCE:
            if not isinstance(condition.source, list) or len(condition.source) != 2:
                return False

            v1: float | None = snapshot.get(condition.source[0])
            v2: float | None = snapshot.get(condition.source[1])
            if v1 is None or v2 is None:
                return False
            measured_value: float = abs(v1 - v2)

        elif condition.type == ConditionType.THRESHOLD:
            if not isinstance(condition.source, str):
                return False
            measured_value = snapshot.get(condition.source)
            if measured_value is None:
                return False

        else:
            return False

        return self._apply_operator(measured_value, condition.threshold, condition.operator)

    def _apply_operator(self, measured_value: float, threshold: float, operator: ConditionOperator) -> bool:
        return {
            ConditionOperator.GREATER_THAN: measured_value > threshold,
            ConditionOperator.LESS_THAN: measured_value < threshold,
            ConditionOperator.EQUAL: measured_value == threshold,
        }[operator]
