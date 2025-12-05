import logging
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from model.enum.alert_enum import AlertSeverity
from model.enum.condition_enum import ConditionType
from schema.alert_schema import AlertConditionModel, ModelConfig

logger = logging.getLogger("AlertConfig")


class AlertConfig(BaseModel):
    """
    Enhanced AlertConfig with validation, merging, and deduplication.

    Features:
    - Version management with semantic versioning
    - Comprehensive validation for all alert types
    - Merging of default_alerts and instance alerts
    - Deduplication by alert code
    - Detailed logging for configuration issues
    """

    # Version management
    version: str = Field(default="1.0.0", description="Configuration file version")
    root: dict[str, ModelConfig]

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        """Validate version format (semantic versioning)"""
        if not re.match(r"^\d+\.\d+\.\d+$", v):
            logger.warning(f"[ALERT_CONFIG] Version '{v}' does not follow semantic versioning (x.y.z)")
        return v

    @model_validator(mode="after")
    def validate_alert_structures(self):
        """Validate all alert configurations in the file"""
        validation_errors = []

        for model_name, model_config in self.root.items():
            # Validate default alerts
            for i, alert in enumerate(model_config.default_alerts):
                errors = self._validate_single_alert(alert, f"{model_name}.default_alerts[{i}]")
                validation_errors.extend(errors)

            # Validate instance alerts
            for instance_id, instance_config in model_config.instances.items():
                if instance_config.alerts:
                    for i, alert in enumerate(instance_config.alerts):
                        errors = self._validate_single_alert(
                            alert, f"{model_name}.instances[{instance_id}].alerts[{i}]"
                        )
                        validation_errors.extend(errors)

        # Log all validation errors (soft validation)
        if validation_errors:
            for error in validation_errors:
                logger.warning(f"[ALERT_CONFIG] {error}")

        return self

    def _validate_single_alert(self, alert: AlertConditionModel, context: str) -> list[str]:
        """Validate a single alert configuration"""
        errors = []

        # Validate alert code exists and is not empty
        if not alert.code or not alert.code.strip():
            errors.append(f"{context}: alert code is missing or empty")

        # Validate sources are not empty
        if not alert.sources:
            errors.append(f"{context}: sources list is empty")

        # Type-specific validations
        alert_type = alert.type

        # Threshold alerts should ideally have single source (warning only)
        if alert_type == ConditionType.THRESHOLD and len(alert.sources) > 1:
            errors.append(
                f"{context}: threshold alert '{alert.code}' has multiple sources ({len(alert.sources)}), "
                f"consider using aggregate type"
            )

        # Aggregate alerts require multiple sources (this should be caught by schema, but double-check)
        if alert_type in [ConditionType.AVERAGE, ConditionType.SUM, ConditionType.MIN, ConditionType.MAX]:
            if len(alert.sources) < 2:
                errors.append(
                    f"{context}: aggregate alert '{alert.code}' requires at least 2 sources, "
                    f"got {len(alert.sources)}"
                )

        # Schedule expected state alerts require exactly one source
        if alert_type == ConditionType.SCHEDULE_EXPECTED_STATE and len(alert.sources) != 1:
            errors.append(
                f"{context}: schedule_expected_state alert '{alert.code}' requires exactly 1 source, "
                f"got {len(alert.sources)}"
            )

        # Validate severity is appropriate
        if alert.severity not in AlertSeverity:
            errors.append(f"{context}: invalid severity '{alert.severity}' for alert '{alert.code}'")

        return errors

    def get_instance_alerts(self, model: str, slave_id: str, deduplicate: bool = True) -> list[AlertConditionModel]:
        """
        Return the list of alert conditions for the given (model, slave_id).

        Rules:
        1) Merge:
           - default_alerts (only if instance.use_default_alerts is True)
           - instance.alerts (if exists)
        2) Filter out invalid alerts:
           - alerts with missing code
           - alerts with empty sources
        3) Deduplicate by alert code (optional, default: True):
           - Keep only the last alert with the same code
           - Instance alerts override default alerts
        4) Preserve definition order after deduplication

        Args:
            model: Device model name
            slave_id: Device instance ID
            deduplicate: Whether to remove duplicate alert codes (default: True)

        Returns:
            List of valid AlertConditionModel instances
        """
        model_config = self.root.get(model)
        if not model_config:
            logger.debug(f"[AlertConfig] Model '{model}' not found in configuration")
            return []

        instance_id = str(slave_id)
        instance_config = model_config.instances.get(instance_id)
        if not instance_config:
            logger.debug(f"[AlertConfig] Instance '{model}_{instance_id}' not found in configuration")
            return []

        # 1) Merge alerts
        merged_alerts: list[AlertConditionModel] = []

        if instance_config.use_default_alerts:
            merged_alerts.extend(model_config.default_alerts)
            logger.debug(f"[{model}_{instance_id}] Using {len(model_config.default_alerts)} default alerts")

        if instance_config.alerts:
            merged_alerts.extend(instance_config.alerts)
            logger.debug(f"[{model}_{instance_id}] Added {len(instance_config.alerts)} instance alerts")

        if not merged_alerts:
            logger.debug(f"[{model}_{instance_id}] No alerts configured")
            return []

        # 2) Filter invalid alerts
        filtered_alerts: list[AlertConditionModel] = []
        for alert in merged_alerts:
            alert_code = alert.code or "<unknown>"
            context = f"[{model}_{instance_id}]"

            # Check alert code
            if not alert.code or not alert.code.strip():
                logger.warning(f"{context} Skipping alert with missing code")
                continue

            # Check sources
            if not alert.sources:
                logger.warning(f"{context} Skipping alert '{alert_code}': no sources defined")
                continue

            # Additional runtime validation
            try:
                # Verify sources count based on alert type
                if alert.type == ConditionType.SCHEDULE_EXPECTED_STATE and len(alert.sources) != 1:
                    logger.warning(
                        f"{context} Skipping alert '{alert_code}': "
                        f"schedule_expected_state requires exactly 1 source, got {len(alert.sources)}"
                    )
                    continue

                if alert.type in [ConditionType.AVERAGE, ConditionType.SUM, ConditionType.MIN, ConditionType.MAX]:
                    if len(alert.sources) < 2:
                        logger.warning(
                            f"{context} Skipping alert '{alert_code}': "
                            f"{alert.type.value} requires at least 2 sources, got {len(alert.sources)}"
                        )
                        continue

            except Exception as e:
                logger.error(f"{context} Skipping alert '{alert_code}': validation error - {str(e)}")
                continue

            filtered_alerts.append(alert)

        if not filtered_alerts:
            logger.info(f"[{model}_{instance_id}] No valid alerts after filtering")
            return filtered_alerts

        # 3) Deduplicate by alert code (if enabled)
        if not deduplicate:
            return filtered_alerts

        seen_codes: set[str] = set()
        deduped_reversed: list[AlertConditionModel] = []
        dropped_alerts: list[str] = []

        # Process in reverse to keep the *last* occurrence (instance overrides default)
        for alert in reversed(filtered_alerts):
            if alert.code in seen_codes:
                dropped_alerts.append(alert.code)
                continue
            seen_codes.add(alert.code)
            deduped_reversed.append(alert)

        # 4) Restore original order
        deduplicated_alerts = list(reversed(deduped_reversed))

        if dropped_alerts:
            logger.warning(
                f"[{model}_{instance_id}] ALERT CODE CONFLICT: "
                f"Dropped duplicate alert codes: {sorted(set(dropped_alerts))}. "
                f"Instance alerts override default alerts with same code. "
                f"Consider using unique codes or setting use_default_alerts=false"
            )

        logger.info(
            f"[{model}_{instance_id}] Loaded {len(deduplicated_alerts)} alerts "
            f"(filtered: {len(merged_alerts) - len(filtered_alerts)}, "
            f"duplicates: {len(dropped_alerts)})"
        )

        return deduplicated_alerts

    def get_all_alert_codes(self, model: str, slave_id: str) -> set[str]:
        """
        Get all unique alert codes for a given instance (useful for debugging).

        Returns:
            Set of alert codes configured for this instance
        """
        alerts = self.get_instance_alerts(model, slave_id, deduplicate=False)
        return {alert.code for alert in alerts if alert.code}

    def has_alerts(self, model: str, slave_id: str) -> bool:
        """
        Quick check if an instance has any alerts configured.

        Returns:
            True if instance has at least one valid alert
        """
        return len(self.get_instance_alerts(model, slave_id)) > 0

    def get_alerts_by_severity(self, model: str, slave_id: str, severity: AlertSeverity) -> list[AlertConditionModel]:
        """
        Get all alerts of a specific severity level.

        Args:
            model: Device model name
            slave_id: Device instance ID
            severity: Alert severity to filter by

        Returns:
            List of alerts matching the severity level
        """
        all_alerts = self.get_instance_alerts(model, slave_id)
        return [alert for alert in all_alerts if alert.severity == severity]

    def get_stats(self) -> dict[str, Any]:
        """
        Get configuration statistics for debugging/monitoring.

        Returns:
            Dictionary with configuration statistics
        """
        stats = {"version": self.version, "total_models": len(self.root), "models": {}}

        for model_name, model_config in self.root.items():
            model_stats = {
                "default_alerts": len(model_config.default_alerts),
                "instances": len(model_config.instances),
                "instance_details": {},
            }

            for instance_id, instance_config in model_config.instances.items():
                instance_alerts = instance_config.alerts or []
                model_stats["instance_details"][instance_id] = {
                    "use_default_alerts": instance_config.use_default_alerts,
                    "instance_alerts": len(instance_alerts),
                    "total_effective": len(self.get_instance_alerts(model_name, instance_id)),
                }

            stats["models"][model_name] = model_stats

        return stats
