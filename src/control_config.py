import logging

from pydantic import BaseModel, Field

from model.control_model import ControlConditionModel

logger = logging.getLogger("ControlConfig")


class ControlInstanceConfig(BaseModel):
    use_default_controls: bool = False
    controls: list[ControlConditionModel] = Field(default_factory=list)


class ControlModelConfig(BaseModel):
    default_controls: list[ControlConditionModel] = Field(default_factory=list)
    # Recommend adding default_factory to avoid parse errors when instances is not declared
    instances: dict[str, ControlInstanceConfig] = Field(default_factory=dict)


class ControlConfig(BaseModel):
    root: dict[str, ControlModelConfig]

    def get_control_list(self, model: str, slave_id: str) -> list[ControlConditionModel]:
        """
        Return the list of control conditions for the given (model, slave_id).

        Rules:
          1) Merge:
             - default_controls (only if instance.use_default_controls is True)
             - instance.controls
          2) Filter out invalid rules (skip with warnings):
             - composite is None (invalid composite)
             - action is None or action.type is missing
          3) Deduplicate by priority (keep only the last one; instance overrides default)
          4) Preserve definition order after dedup
        """
        model_config = self.root.get(model)
        if not model_config:
            return []

        instance_id = str(slave_id)
        instance_config = model_config.instances.get(instance_id)
        if not instance_config:
            return []

        # 1) Merge controls
        merged_control_list: list[ControlConditionModel] = []
        if instance_config.use_default_controls:
            merged_control_list.extend(model_config.default_controls)
        merged_control_list.extend(instance_config.controls)

        # 2) Filter invalid (log + skip)
        filtered_control_list: list[ControlConditionModel] = []
        for rule in merged_control_list:
            rid = getattr(rule, "code", getattr(rule, "name", "<unknown>"))
            comp = getattr(rule, "composite", None)

            # composite missing or null
            if comp is None:
                logger.warning(f"[{model}_{instance_id}] skip rule '{rid}': missing or null composite")
                continue

            # composite structure invalid (flagged by CompositeNode's after validator)
            if getattr(comp, "invalid", False):
                logger.warning(f"[{model}_{instance_id}] skip rule '{rid}': invalid composite")
                continue

            # action/type missing
            act = getattr(rule, "action", None)
            if act is None or getattr(act, "type", None) is None:
                logger.error(f"[{model}_{instance_id}] skip rule '{rid}': missing action.type")
                continue

            filtered_control_list.append(rule)

        if not filtered_control_list:
            return []

        # 3) Deduplicate by priority (keep the *last* one)
        seen_priorities: set[int] = set()
        deduped_reversed: list[ControlConditionModel] = []
        dropped_rules: list[tuple[int, str]] = []

        for rule in reversed(filtered_control_list):
            priority: int = rule.priority
            rule_identifier = getattr(rule, "code", getattr(rule, "name", "<unknown>"))
            if priority in seen_priorities:
                dropped_rules.append((priority, rule_identifier))
                continue
            seen_priorities.add(priority)
            deduped_reversed.append(rule)

        deduplicated_controls: list[ControlConditionModel] = list(reversed(deduped_reversed))  # 4) restore order

        if dropped_rules:
            logger.warning(
                f"[{model}_{instance_id}] duplicate priorities resolved; kept later rule, "
                f"dropped={sorted(dropped_rules)}"
            )

        return deduplicated_controls
