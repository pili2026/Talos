from control_config import ControlConfig
from model.condition_enum import ConditionOperator, ConditionType
from model.control_model import ControlActionModel, ControlConditionModel


class ControlEvaluator:
    def __init__(self, control_config: ControlConfig):
        self.control_config = control_config

    def evaluate(self, model: str, slave_id: str, snapshot: dict[str, float]) -> list[ControlActionModel]:
        action_list: list[ControlActionModel] = []
        condition_list = self.control_config.get_control_list(model, slave_id)
        sorted_conditions = sorted(condition_list, key=lambda c: c.priority, reverse=True)

        for condition in sorted_conditions:
            if self._check_condition(condition, snapshot):
                action_list.append(condition.action)
        return action_list

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
