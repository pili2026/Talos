from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from core.model.enum.condition_enum import ControlPolicyType
from core.model.enum.priority_range_enum import ControlPriority
from core.schema.control_condition_schema import ConditionSchema

logger = logging.getLogger("ControlConfig")


class ControlInstanceConfig(BaseModel):
    use_default_controls: bool = False
    controls: list[ConditionSchema] = Field(default_factory=list)


class ControlModelConfig(BaseModel):
    default_controls: list[ConditionSchema] = Field(default_factory=list)
    instances: dict[str, ControlInstanceConfig] = Field(default_factory=dict)


class ControlConfig(BaseModel):
    """
    Control condition configuration

    DEPRECATED: The 'root' wrapper will be removed in future versions.
    Please update your config files to use the flat structure without 'root'.
    """

    version: str = Field(default="1.0.0", description="Configuration file version")
    root: dict[str, ControlModelConfig]

    @field_validator("version")
    @classmethod
    def validate_version(cls, v):
        """Validate version format (basic semantic versioning)"""
        if not re.match(r"^\d+\.\d+\.\d+$", v):
            logger.warning(f"[CONFIG] Version '{v}' does not follow semantic versioning (x.y.z)")
        return v

    @model_validator(mode="before")
    @classmethod
    def normalize_structure(cls, data: Any) -> Any:
        """
        Normalize config structure to always have 'root' key

        This validator runs BEFORE parsing and wraps device models under 'root'
        if they're at the top level (legacy format support).
        """
        if not isinstance(data, dict):
            return data

        # If already has 'root' key, return as-is
        if "root" in data:
            logger.debug("[CONFIG] Config already has 'root' key")
            return data

        # Legacy format: wrap device models under 'root'
        version = data.get("version", "1.0.0")

        # All other keys are device models, wrap them under 'root'
        device_models = {k: v for k, v in data.items() if k != "version"}

        if device_models:
            logger.debug(
                f"[CONFIG] Auto-wrapping {len(device_models)} device models under 'root' key "
                f"(legacy format support)"
            )

        return {"version": version, "root": device_models}

    @model_validator(mode="after")
    def validate_composite_structures(self):
        """
        Validate all composite structures and priority assignments

        This validator runs after the model is fully constructed and checks:
        1. Composite structure validity
        2. Priority assignment safety rules
        3. Policy compatibility
        """
        validation_errors = []
        validation_warnings = []

        for model_name, model_config in self.root.items():
            # Validate default controls
            for i, control in enumerate(model_config.default_controls):
                errors, warnings = self._validate_single_control(control, f"{model_name}.default_controls[{i}]")
                validation_errors.extend(errors)
                validation_warnings.extend(warnings)

            # Validate instance controls
            for instance_id, instance_config in model_config.instances.items():
                for i, control in enumerate(instance_config.controls):
                    errors, warnings = self._validate_single_control(
                        control, f"{model_name}.instances[{instance_id}].controls[{i}]"
                    )
                    validation_errors.extend(errors)
                    validation_warnings.extend(warnings)

        # Log validation warnings (soft validation - allow loading)
        if validation_warnings:
            for warning in validation_warnings:
                logger.warning(f"[CONFIG] {warning}")

        # Validation errors (hard validation - block loading)
        if validation_errors:
            for error in validation_errors:
                logger.error(f"[CONFIG] {error}")

            # Raise exception to block loading
            error_summary = "\n  ".join(["Configuration validation failed:"] + validation_errors)
            raise ValueError(error_summary)

        return self

    def _validate_single_control(self, control: ConditionSchema, context: str) -> tuple[list[str], list[str]]:
        """
        Validate a single control's composite structure and priority

        Args:
            control: Control condition to validate
            context: Context string for error messages

        Returns:
            Tuple of (errors, warnings)
            - errors: Critical issues that block config loading
            - warnings: Issues that should be fixed but don't block loading
        """
        errors = []
        warnings = []

        # Composite structure validation
        if control.composite and control.composite.invalid:
            errors.append(f"{context}: composite structure failed validation")

        # Check composite depth
        if control.composite:
            try:
                depth = control.composite.calculate_max_depth()
                if depth == -1:
                    errors.append(f"{context}: circular reference in composite structure")
                elif depth > 15:
                    errors.append(f"{context}: composite depth ({depth}) exceeds runtime limit (15)")
            except Exception as e:
                error_msg = str(e)
                if "Circular reference" in error_msg:
                    errors.append(f"{context}: circular reference in composite")
                elif "depth" in error_msg.lower() and "exceed" in error_msg.lower():
                    errors.append(f"{context}: composite depth exceeded limit")
                else:
                    errors.append(f"{context}: composite structure error - {error_msg}")

        # Policy compatibility validation
        if control.policy and control.policy.type:
            policy_errors = self._validate_policy_composite_compatibility(
                control.policy.type, control.composite, context
            )
            errors.extend(policy_errors)

        # Priority validation
        priority_errors, priority_warnings = ControlPriority.validate_safety_rules(control, context)
        errors.extend(priority_errors)
        warnings.extend(priority_warnings)

        return errors, warnings

    def _validate_policy_composite_compatibility(
        self, policy_type: ControlPolicyType, composite, context: str
    ) -> list[str]:
        """Check if policy type is compatible with composite complexity"""
        errors = []

        # Example business rule: discrete_setpoint with overly complex conditions
        if policy_type == ControlPolicyType.DISCRETE_SETPOINT:
            if composite:
                depth = composite.calculate_max_depth()
                if depth == -1:
                    errors.append(f"{context}: circular reference in discrete_setpoint composite")
                elif depth > 5:
                    errors.append(
                        f"{context}: discrete_setpoint policy with deep nesting ({depth} levels) "
                        f"may indicate design issues"
                    )

        return errors

    def get_control_list(self, model: str, slave_id: str) -> list[ConditionSchema]:
        """
        Return validated and deduplicated control conditions.

        Note: This method is called at runtime, not at config load time.
        Priority validation has already been performed during config loading.
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

        # Warn on overlap
        self._check_active_time_range_overlaps(valid_controls, model, instance_id)

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

            filtered.append(rule)

        return filtered

    def _deduplicate_by_priority(
        self, rules: list[ConditionSchema], model: str, instance_id: str
    ) -> list[ConditionSchema]:
        """
        Deduplicate by priority (last-write-wins).

        Priority must be unique within a single device's control rules.
        This ensures clear execution order and protection behavior.
        """
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
                f"[{model}_{instance_id}] PRIORITY CONFLICT: "
                f"Dropped {len(dropped)} rule(s) due to duplicate priority: {sorted(dropped)}"
            )
            logger.error(
                f"[{model}_{instance_id}] Each rule must have a unique priority value. "
                f"Please assign different priorities to avoid conflicts."
            )

        return deduplicated

    def _check_active_time_range_overlaps(self, rules: list[ConditionSchema], model: str, instance_id: str) -> None:
        """
        Route-2 semantics:
        - Overlapping active_time_ranges do NOT block loading.
        - Log a WARNING to surface potentially redundant or misconfigured ranges.
        """
        context = f"[{model}_{instance_id}]"

        for rule in rules:
            active_ranges = rule.active_time_ranges

            # None or [] means "always active" → no overlap semantics
            if not active_ranges or len(active_ranges) < 2:
                continue

            time_windows: list[tuple[int, int, str]] = []

            for time_range in active_ranges:
                try:
                    start_min = self._parse_time_of_day_to_minutes(time_range.start)
                    end_min = self._parse_time_of_day_to_minutes(time_range.end)
                except Exception:
                    rule_id = rule.code or rule.name or "<unknown>"
                    logger.warning(
                        f"{context} rule '{rule_id}': invalid active_time_ranges format; " f"overlap check skipped"
                    )
                    time_windows = []
                    break

                # Cross-day or invalid range (not supported yet)
                if end_min <= start_min:
                    rule_id = rule.code or rule.name or "<unknown>"
                    logger.warning(
                        f"{context} rule '{rule_id}': active_time_ranges contains "
                        f"cross-day or invalid range ({time_range.start}~{time_range.end}); "
                        f"overlap check skipped"
                    )
                    time_windows = []
                    break

                time_windows.append((start_min, end_min, f"{time_range.start}~{time_range.end}"))

            if not time_windows:
                continue

            # Sort by start time
            time_windows.sort(key=lambda w: w[0])

            overlaps: list[tuple[str, str]] = []

            prev_start, prev_end, prev_label = time_windows[0]
            for curr_start, curr_end, curr_label in time_windows[1:]:
                if curr_start < prev_end:
                    overlaps.append((prev_label, curr_label))
                    prev_end = max(prev_end, curr_end)
                    prev_label = f"{prev_label} + {curr_label}"
                else:
                    prev_start, prev_end, prev_label = curr_start, curr_end, curr_label

            if overlaps:
                rule_id = rule.code or rule.name or "<unknown>"
                logger.warning(
                    f"{context} rule '{rule_id}': active_time_ranges overlap detected: {overlaps}. "
                    f"Ranges are OR-ed; consider merging or simplifying."
                )

    @staticmethod
    def _parse_time_of_day_to_minutes(time_str: str) -> int:
        """
        Parse a time-of-day string ('HH:MM') into minutes since 00:00.
        """
        if not isinstance(time_str, str) or ":" not in time_str:
            raise ValueError(f"Invalid time format: {time_str}")

        hour_str, minute_str = time_str.split(":", 1)
        hour = int(hour_str)
        minute = int(minute_str)

        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"Invalid time value: {time_str}")

        return hour * 60 + minute
