from model.condition_enum import ConditionOperator, ConditionType
from model.control_model import ControlActionModel, ControlConditionModel


class ControlEvaluator:
    def __init__(self, control_config: dict):

        self.device_controls_map: dict[str, list[ControlConditionModel]] = {}
        for device_id, conf in control_config.items():
            control_list = conf.get("controls", [])
            validated = [ControlConditionModel(**c) for c in control_list]
            self.device_controls_map[device_id] = validated

    def evaluate(self, device_id: str, snapshot: dict[str, float]) -> list[ControlActionModel]:
        action_list = []
        control_condition_list = self.device_controls_map.get(device_id, [])
        for condition in control_condition_list:
            if self._check_condition(condition, snapshot):
                action_list.append(condition.action)
        return action_list

    def _check_condition(self, condition: ControlConditionModel, snapshot: dict[str, float]) -> bool:
        if condition.condition_type == ConditionType.DIFFERENCE:
            v1: float | None = snapshot.get(condition.source[0])
            v2: float | None = snapshot.get(condition.source[1])
            if v1 is None or v2 is None:
                return False
            measured_value: float = v1 - v2
        elif condition.condition_type == ConditionType.THRESHOLD:
            measured_value: float = snapshot.get(condition.source)
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
