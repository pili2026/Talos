from dataclasses import dataclass
from typing import Any


@dataclass
class ControlAction:
    trigger_device_id: str
    device_id: str
    type: str
    target: str
    value: Any


class ControlEvaluator:
    def __init__(self, control_config: dict):
        self.control_config = control_config

    def evaluate(self, device_id: str, snapshot: dict) -> list[ControlAction]:
        actions = []
        cfg = self.control_config.get(device_id)
        if not cfg:
            return actions

        controls: list[dict] = cfg.get("controls", [])
        for control in controls:
            if self._check_condition(control, snapshot):
                action_cfg = control["action"]
                action = ControlAction(
                    trigger_device_id=device_id,
                    device_id=action_cfg["device_id"],
                    type=action_cfg["type"],
                    target=action_cfg.get("target", "frequency"),
                    value=action_cfg["value"],
                )
                actions.append(action)
        return actions

    def _check_condition(self, cond: dict, dev_data: dict) -> bool:
        t = cond.get("type")
        op = cond.get("condition")
        threshold = cond.get("threshold")

        if t == "difference":
            pins = cond["pins"]
            v1 = dev_data.get(pins[0])
            v2 = dev_data.get(pins[1])
            if v1 is None or v2 is None:
                return False
            diff = v1 - v2
        else:  # threshold type
            pin = cond["pin"]
            diff = dev_data.get(pin)
            if diff is None:
                return False

        return self._apply_condition(diff, threshold, op)

    def _apply_condition(self, val, threshold, op) -> bool:
        if op == "gt":
            return val > threshold
        if op == "lt":
            return val < threshold
        if op == "eq":
            return val == threshold
        return False
