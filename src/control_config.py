import logging

from pydantic import BaseModel, Field

from model.control_model import ControlConditionModel

logger = logging.getLogger("ControlConfig")


class ControlInstanceConfig(BaseModel):
    use_default_controls: bool = False
    controls: list[ControlConditionModel] = Field(default_factory=list)


class ControlModelConfig(BaseModel):
    default_controls: list[ControlConditionModel] = Field(default_factory=list)
    instances: dict[str, ControlInstanceConfig]


class ControlConfig(BaseModel):
    root: dict[str, ControlModelConfig]

    def get_control_list(self, model: str, slave_id: str) -> list[ControlConditionModel]:
        """
        Return the list of control conditions for the given (model, slave_id).

        Rules:
          1) Merge according to requirements:
             - default_controls (optional, only if instance.use_default_controls is True)
             - instance.controls
          2) Deduplicate by priority:
             - If multiple controls share the same priority, keep only the *last* one
               (ensures instance overrides default).
          3) Preserve the original definition order:
             - This makes it more intuitive when Evaluator uses index-based resolution.

        :param model: The model name (key in root).
        :param slave_id: The slave identifier, used to look up the instance config.
        :return: A list of ControlConditionModel objects, merged and deduplicated.
        """
        model_config = self.root.get(model)
        if not model_config:
            return []

        instance_id = str(slave_id)
        instance_config = model_config.instances.get(instance_id)
        if not instance_config:
            return []

        # Merger controls
        merged_controls: list[ControlConditionModel] = []
        if instance_config.use_default_controls:
            merged_controls.extend(model_config.default_controls)
        merged_controls.extend(instance_config.controls)

        # Deduplicate by priority (keep only the last one)
        seen_priorities: set[int] = set()
        deduped_reversed: list[ControlConditionModel] = []
        dropped_rules: list[tuple[int, str]] = []

        for rule in reversed(merged_controls):
            priority: int = rule.priority
            rule_identifier = getattr(rule, "code", rule.name)
            if priority in seen_priorities:
                dropped_rules.append((priority, rule_identifier))
                continue
            seen_priorities.add(priority)
            deduped_reversed.append(rule)

        deduplicated_controls: list[ControlConditionModel] = list(reversed(deduped_reversed))  # Restore original order

        if dropped_rules:
            logger.warning(
                f"[{model}_{instance_id}] duplicate priorities resolved; kept later rule, dropped={sorted(dropped_rules)}"
            )

        return deduplicated_controls
