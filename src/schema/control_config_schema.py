import logging

from pydantic import BaseModel, Field, field_validator, model_validator

from schema.control_condition_schema import ConditionSchema
from model.enum.condition_enum import ControlPolicyType

logger = logging.getLogger("ControlConfig")


class ControlInstanceConfig(BaseModel):
    use_default_controls: bool = False
    controls: list[ConditionSchema] = Field(default_factory=list)


class ControlModelConfig(BaseModel):
    default_controls: list[ConditionSchema] = Field(default_factory=list)
    # Recommend adding default_factory to avoid parse errors when instances is not declared
    instances: dict[str, ControlInstanceConfig] = Field(default_factory=dict)


class ControlConfig(BaseModel):
    # Version management
    version: str = Field(default="1.0.0", description="Configuration file version")
    root: dict[str, ControlModelConfig]

    @field_validator("version")
    @classmethod
    def validate_version(cls, v):
        """Validate version format (basic semantic versioning)"""
        import re

        if not re.match(r"^\d+\.\d+\.\d+$", v):
            logger.warning(f"[CONFIG] Version '{v}' does not follow semantic versioning (x.y.z)")
        return v

    @model_validator(mode="after")
    def validate_composite_structures(self):
        """Validate all composite structures in the configuration"""
        validation_errors = []

        for model_name, model_config in self.root.items():
            # Validate default controls
            for i, control in enumerate(model_config.default_controls):
                errors = self._validate_single_control(control, f"{model_name}.default_controls[{i}]")
                validation_errors.extend(errors)

            # Validate instance controls
            for instance_id, instance_config in model_config.instances.items():
                for i, control in enumerate(instance_config.controls):
                    errors = self._validate_single_control(
                        control, f"{model_name}.instances[{instance_id}].controls[{i}]"
                    )
                    validation_errors.extend(errors)

        # Log validation errors (soft validation approach)
        if validation_errors:
            for error in validation_errors:
                logger.warning(f"[CONFIG] Composite structure validation: {error}")

        return self

    def _validate_single_control(self, control: ConditionSchema, context: str) -> list[str]:
        """Validate a single control's composite structure"""
        errors = []

        if not control.composite:
            return errors

        # Check if composite was marked as invalid during its own validation
        if control.composite.invalid:
            errors.append(f"{context}: composite structure failed validation")

        # Additional business logic validations
        if control.policy and control.policy.type:
            policy_errors = self._validate_policy_composite_compatibility(
                control.policy.type, control.composite, context
            )
            errors.extend(policy_errors)

        return errors

    def _validate_policy_composite_compatibility(self, policy_type, composite, context: str) -> list[str]:
        """Check if policy type is compatible with composite complexity"""

        errors = []

        # Example business rule: discrete_setpoint with overly complex conditions might be suspicious
        if policy_type == ControlPolicyType.DISCRETE_SETPOINT:
            depth = composite.calculate_max_depth()
            if depth == -1:
                errors.append(f"{context}: circular reference in discrete_setpoint composite")
            elif depth > 5:  # More restrictive for discrete policies
                errors.append(
                    f"{context}: discrete_setpoint policy with deep nesting ({depth} levels) may indicate design issues"
                )

        return errors

    def get_control_list(self, model: str, slave_id: str) -> list[ConditionSchema]:
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
        merged_control_list: list[ConditionSchema] = []
        if instance_config.use_default_controls:
            merged_control_list.extend(model_config.default_controls)
        merged_control_list.extend(instance_config.controls)

        # 2) Filter invalid (log + skip) - Enhanced validation
        filtered_control_list: list[ConditionSchema] = []
        for rule in merged_control_list:
            rid = rule.code or rule.name or "<unknown>"
            context = f"[{model}_{instance_id}]"

            if rule.composite is None:
                logger.warning(f"{context} skip rule '{rid}': missing or null composite")
                continue
            if rule.composite.invalid:
                logger.warning(f"{context} skip rule '{rid}': invalid composite structure")
                continue
            if rule.action is None or rule.action.type is None:
                logger.error(f"{context} skip rule '{rid}': missing action.type")
                continue
            if rule.policy and rule.policy.invalid:
                logger.warning(f"{context} skip rule '{rid}': invalid policy configuration")
                continue

            # Additional runtime validation
            try:
                # Ensure composite depth is within runtime limits (might be different from config limits)
                depth = rule.composite.calculate_max_depth()
                if depth > 15:  # More generous runtime limit
                    logger.error(f"{context} skip rule '{rid}': composite depth ({depth}) exceeds runtime limit")
                    continue
            except Exception as e:
                # Handle specific exceptions with more descriptive messages
                if "Circular reference detected" in str(e):
                    logger.error(f"{context} skip rule '{rid}': circular reference in composite structure")
                elif "depth" in str(e).lower() and "exceed" in str(e).lower():
                    logger.error(f"{context} skip rule '{rid}': composite depth exceeded limit")
                else:
                    logger.error(f"{context} skip rule '{rid}': composite structure error - {str(e)}")
                continue

            filtered_control_list.append(rule)

        if not filtered_control_list:
            return []

        # 3) Deduplicate by priority (keep the *last* one)
        seen_priorities: set[int] = set()
        deduped_reversed: list[ConditionSchema] = []
        dropped_rules: list[tuple[int, str]] = []

        for rule in reversed(filtered_control_list):
            priority: int = rule.priority
            rule_identifier = rule.code or rule.name or "<unknown>"
            if priority in seen_priorities:
                dropped_rules.append((priority, rule_identifier))
                continue
            seen_priorities.add(priority)
            deduped_reversed.append(rule)

        deduplicated_controls: list[ConditionSchema] = list(reversed(deduped_reversed))  # 4) restore order

        if dropped_rules:
            logger.error(
                f"[{model}_{instance_id}] PRIORITY CONFLICT: "
                f"instance controls override default controls at same priority. "
                f"Dropped rules: {sorted(dropped_rules)}. "
                f"To fix: use different priorities or set use_default_controls=false"
            )

        return deduplicated_controls
