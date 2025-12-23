import logging
import re

from pydantic import BaseModel, Field, field_validator, model_validator

from core.model.enum.condition_enum import ControlPolicyType
from core.schema.control_condition_schema import ConditionSchema

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
        Return validated and deduplicated control conditions.
        """
        model_config = self.root.get(model)
        if not model_config:
            return []

        instance_id = str(slave_id)
        instance_config = model_config.instances.get(instance_id)
        if not instance_config:
            return []

        # Step 1: Merge controls
        merged_controls = self._merge_controls(model_config, instance_config)

        # Step 2: Filter invalid
        valid_controls = self._filter_invalid_rules(merged_controls, model, instance_id)

        if not valid_controls:
            return []

        # Step 3: Deduplicate by priority
        deduplicated = self._deduplicate_by_priority(valid_controls, model, instance_id)

        return deduplicated

    def _merge_controls(
        self, model_config: ControlModelConfig, instance_config: ControlInstanceConfig
    ) -> list[ConditionSchema]:
        """Merge default and instance controls."""
        merged = []
        if instance_config.use_default_controls:
            merged.extend(model_config.default_controls)
        merged.extend(instance_config.controls)
        return merged

    def _filter_invalid_rules(
        self, rules: list[ConditionSchema], model: str, instance_id: str
    ) -> list[ConditionSchema]:
        """Filter out invalid rules with detailed logging"""
        filtered: list[ConditionSchema] = []
        context = f"[{model}_{instance_id}]"

        for rule in rules:
            rule_id = rule.code or rule.name or "<unknown>"

            # Check composite
            if rule.composite is None:
                logger.warning(f"{context} skip rule '{rule_id}': missing or null composite")
                continue
            if rule.composite.invalid:
                logger.warning(f"{context} skip rule '{rule_id}': invalid composite structure")
                continue

            # Check actions
            if not rule.actions:
                logger.error(f"{context} skip rule '{rule_id}': no actions defined")
                continue

            # Validate actions
            valid_action_count = 0
            invalid_action_indices = []
            for idx, action in enumerate(rule.actions):
                if action is None or action.type is None:
                    invalid_action_indices.append(idx)
                else:
                    valid_action_count += 1

            if valid_action_count == 0:
                logger.error(
                    f"{context} skip rule '{rule_id}': " f"all {len(rule.actions)} actions are invalid (missing type)"
                )
                continue

            if invalid_action_indices:
                logger.warning(
                    f"{context} rule '{rule_id}': "
                    f"{len(invalid_action_indices)} invalid actions at indices {invalid_action_indices} "
                    f"(will be skipped during execution)"
                )

            # Check policy
            if rule.policy and rule.policy.invalid:
                logger.warning(f"{context} skip rule '{rule_id}': invalid policy configuration")
                continue

            # Validate composite depth
            try:
                depth = rule.composite.calculate_max_depth()
                if depth > 15:
                    logger.error(
                        f"{context} skip rule '{rule_id}': " f"composite depth ({depth}) exceeds runtime limit"
                    )
                    continue
            except Exception as e:
                error_msg = str(e)
                if "Circular reference detected" in error_msg:
                    logger.error(f"{context} skip rule '{rule_id}': circular reference in composite")
                elif "depth" in error_msg.lower() and "exceed" in error_msg.lower():
                    logger.error(f"{context} skip rule '{rule_id}': composite depth exceeded limit")
                else:
                    logger.error(f"{context} skip rule '{rule_id}': composite structure error - {error_msg}")
                continue

            filtered.append(rule)

        return filtered

    def _deduplicate_by_priority(
        self, rules: list[ConditionSchema], model: str, instance_id: str
    ) -> list[ConditionSchema]:
        """Deduplicate by priority (last-write-wins)."""
        seen: set[int] = set()
        deduplicated: list[ConditionSchema] = []
        dropped: list[tuple[int, str]] = []

        # Reverse to keep last occurrence
        for rule in reversed(rules):
            priority = rule.priority if rule.priority is not None else 999

            if priority not in seen:
                seen.add(priority)
                deduplicated.append(rule)
            else:
                rule_id = rule.code or rule.name or "<unknown>"
                dropped.append((priority, rule_id))

        # Restore original order
        deduplicated.reverse()

        # Log conflicts
        if dropped:
            logger.error(
                f"[{model}_{instance_id}] PRIORITY CONFLICT: " f"Dropped {len(dropped)} rule(s): {sorted(dropped)}"
            )

        return deduplicated
