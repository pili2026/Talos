"""
Control Condition Priority Range Definitions

This module defines semantic priority tiers with recommended ranges.
Lower priority number = Higher execution priority.

Design Philosophy:
- HARD RULES: Safety-critical constraints (enforced)
- SOFT RULES: Best practice recommendations (warnings only)
- FLEXIBILITY: Any integer priority allowed within hard rules

Priority Tiers (Recommended Ranges):
- Tier 0 (0-9): Emergency - Safety-critical with emergency_override
- Tier 1 (10-19): Time Override - Time-based fixed control
- Tier 2 (20-79): Equipment Recovery - VFD error handling (60 slots)
- Tier 3 (80-89): Device Control - Equipment on/off control
- Tier 4 (90+): Normal Control - Standard operational adjustments
"""

from enum import IntEnum

from core.schema.control_condition_schema import ConditionSchema


class ControlPriority(IntEnum):
    """
    Control condition priority tier definitions

    Priority Tiers:
    - Emergency (0-9): Safety-critical with emergency_override
    - Time Override (10-19): Time-based fixed control
    - Equipment Recovery (20-79): VFD error handling
    - Device Control (80-89): Equipment on/off
    - Normal Control (90+): Standard adjustments

    """

    # ═══════════════════════════════════════════════════════════
    # Tier Boundaries (Recommended Ranges)
    # ═══════════════════════════════════════════════════════════

    # ────────────────────────────────────────
    # Tier 0: Emergency (0-9) - 10 slots
    # ────────────────────────────────────────
    EMERGENCY_MIN = 0
    EMERGENCY_MAX = 9

    # ────────────────────────────────────────
    # Tier 1: Time Override (10-19) - 10 slots
    # ────────────────────────────────────────
    TIME_OVERRIDE_MIN = 10
    TIME_OVERRIDE_MAX = 19

    # ────────────────────────────────────────
    # Tier 2: Equipment Recovery (20-79) - 60 slots
    # ────────────────────────────────────────
    EQUIPMENT_RECOVERY_MIN = 20
    EQUIPMENT_RECOVERY_MAX = 79

    # ────────────────────────────────────────
    # Tier 3: Device Control (80-89) - 10 slots
    # ────────────────────────────────────────
    DEVICE_CONTROL_MIN = 80
    DEVICE_CONTROL_MAX = 89

    # ────────────────────────────────────────
    # Tier 4: Normal Control (90+) - unlimited
    # ────────────────────────────────────────
    NORMAL_CONTROL_MIN = 90
    # No MAX - can use any value >= 90

    # ═══════════════════════════════════════════════════════════
    # Convenience Constants (Common Starting Points)
    # ═══════════════════════════════════════════════════════════

    EMERGENCY = 0
    """Emergency protection (over-temperature, low-frequency, etc.)"""

    TIME_OVERRIDE = 10
    """Time-based override (fixed frequency during specific hours)"""

    EQUIPMENT_RECOVERY = 20
    """Equipment recovery (VFD error reset, recovery, restart)"""

    DEVICE_CONTROL = 80
    """Device control (temperature-based shutdown/startup)"""

    NORMAL_CONTROL = 90
    """Normal control (speed up/down, standard adjustments)"""

    # ═══════════════════════════════════════════════════════════
    # Tier Check Methods
    # ═══════════════════════════════════════════════════════════

    @classmethod
    def is_emergency_tier(cls, priority: int) -> bool:
        """
        Check if priority is in Emergency tier (0-9)

        Args:
            priority: Priority value to check

        Returns:
            True if in Emergency tier
        """
        return cls.EMERGENCY_MIN <= priority <= cls.EMERGENCY_MAX

    @classmethod
    def is_time_override_tier(cls, priority: int) -> bool:
        """
        Check if priority is in Time Override tier (10-19)

        Args:
            priority: Priority value to check

        Returns:
            True if in Time Override tier
        """
        return cls.TIME_OVERRIDE_MIN <= priority <= cls.TIME_OVERRIDE_MAX

    @classmethod
    def is_equipment_recovery_tier(cls, priority: int) -> bool:
        """
        Check if priority is in Equipment Recovery tier (20-79)

        Args:
            priority: Priority value to check

        Returns:
            True if in Equipment Recovery tier
        """
        return cls.EQUIPMENT_RECOVERY_MIN <= priority <= cls.EQUIPMENT_RECOVERY_MAX

    @classmethod
    def is_device_control_tier(cls, priority: int) -> bool:
        """
        Check if priority is in Device Control tier (80-89)

        Args:
            priority: Priority value to check

        Returns:
            True if in Device Control tier
        """
        return cls.DEVICE_CONTROL_MIN <= priority <= cls.DEVICE_CONTROL_MAX

    @classmethod
    def is_normal_control_tier(cls, priority: int) -> bool:
        """
        Check if priority is in Normal Control tier (90+)

        Args:
            priority: Priority value to check

        Returns:
            True if in Normal Control tier
        """
        return priority >= cls.NORMAL_CONTROL_MIN

    @classmethod
    def get_tier_name(cls, priority: int) -> str:
        """
        Get human-readable tier name for a priority value

        Args:
            priority: Priority value

        Returns:
            Tier name string

        Examples:
            >>> ControlPriority.get_tier_name(0)
            'Emergency (0-9)'
            >>> ControlPriority.get_tier_name(25)
            'Equipment Recovery (20-79)'
            >>> ControlPriority.get_tier_name(150)
            'Normal Control (90+)'
        """
        if cls.is_emergency_tier(priority):
            return f"Emergency ({cls.EMERGENCY_MIN}-{cls.EMERGENCY_MAX})"
        elif cls.is_time_override_tier(priority):
            return f"Time Override ({cls.TIME_OVERRIDE_MIN}-{cls.TIME_OVERRIDE_MAX})"
        elif cls.is_equipment_recovery_tier(priority):
            return f"Equipment Recovery ({cls.EQUIPMENT_RECOVERY_MIN}-{cls.EQUIPMENT_RECOVERY_MAX})"
        elif cls.is_device_control_tier(priority):
            return f"Device Control ({cls.DEVICE_CONTROL_MIN}-{cls.DEVICE_CONTROL_MAX})"
        elif cls.is_normal_control_tier(priority):
            return f"Normal Control ({cls.NORMAL_CONTROL_MIN}+)"
        else:
            return f"Unassigned (priority={priority})"

    @classmethod
    def get_tier_description(cls, priority: int) -> str:
        """
        Get detailed description of the tier

        Args:
            priority: Priority value

        Returns:
            Detailed description of tier's purpose and requirements
        """
        if cls.is_emergency_tier(priority):
            return (
                "Emergency (0-9): Safety-critical conditions. "
                "MUST have emergency_override=True. "
                "Always active (no time restrictions)."
            )
        if cls.is_time_override_tier(priority):
            return (
                "Time Override (10-19): Time-based fixed control. "
                "MUST have active_time_ranges. "
                "Blocks normal control but not emergency."
            )
        if cls.is_equipment_recovery_tier(priority):
            return (
                "Equipment Recovery (20-79): VFD error handling. "
                "Fault reset, recovery, and restart logic. "
                "60 slots available for multiple devices."
            )
        if cls.is_device_control_tier(priority):
            return "Device Control (80-89): Equipment on/off control. " "Temperature-based shutdown/startup."
        if cls.is_normal_control_tier(priority):
            return (
                "Normal Control (90+): Standard operational adjustments. "
                "Speed up/down, normal frequency control. "
                "Unlimited slots available."
            )
        return (
            f"Priority {priority} is outside recommended ranges. "
            "Consider using defined tier ranges for better organization."
        )

    # ═══════════════════════════════════════════════════════════
    # Validation Methods
    # ═══════════════════════════════════════════════════════════

    @classmethod
    def validate_safety_rules(cls, rule: "ConditionSchema", context: str = "") -> tuple[list[str], list[str]]:
        """
        Validate priority assignment against safety rules

        Args:
            rule: Control condition to validate
            context: Context string for error messages (e.g., "TECO_VFD.instances[1]")

        Returns:
            Tuple of (errors, warnings)
            - errors: MUST fix - blocks config loading
            - warnings: SHOULD fix - logged but allows loading

        Hard Rules (Errors):
        ────────────────────
        1. emergency_override=True → priority < TIME_OVERRIDE_MIN
           - Emergency must have highest priority
           - Cannot be blocked by time-based conditions

        2. active_time_ranges → priority >= TIME_OVERRIDE_MIN
           - Time-based conditions cannot block emergency
           - Must allow emergency conditions to execute

        Soft Rules (Warnings):
        ─────────────────────
        1. Time-based conditions should use Time Override tier (10-19)
        2. Emergency conditions without emergency_override should explain why
        3. Priorities outside defined ranges get organizational suggestions

        Examples:
        ────────
        ```python
                # Valid emergency
                rule = ConditionSchema(
                    priority=0,
                    actions=[ControlActionSchema(emergency_override=True)]
                )
                errors, warnings = ControlPriority.validate_safety_rules(rule)
                # errors = [], warnings = []

                # Invalid: emergency with high priority
                rule = ConditionSchema(
                    priority=50,
                    actions=[ControlActionSchema(emergency_override=True)]
                )
                errors, warnings = ControlPriority.validate_safety_rules(rule)
                # errors = ["emergency_override=True requires priority < 10, got 50"]

                # Invalid: time-based blocking emergency
                rule = ConditionSchema(
                    priority=0,
                    active_time_ranges=[TimeRange(start="09:00", end="12:00")]
                )
                errors, warnings = ControlPriority.validate_safety_rules(rule)
                # errors = ["active_time_ranges requires priority >= 10, got 0"]
        ```
        """
        errors = []
        warnings = []

        rule_id: str = rule.code or rule.name or "<unknown>"
        priority: int = rule.priority if rule.priority is not None else 999

        # Context prefix for error messages
        prefix: str = f"{context}.{rule_id}" if context else rule_id

        # ═══════════════════════════════════════════════════════
        # Detect Rule Characteristics
        # ═══════════════════════════════════════════════════════

        has_emergency: bool = any(action.emergency_override for action in rule.actions)

        has_time_ranges: bool = rule.active_time_ranges is not None and len(rule.active_time_ranges) > 0

        # ═══════════════════════════════════════════════════════
        # HARD RULES (Safety Critical - Block Loading)
        # ═══════════════════════════════════════════════════════

        # Rule 1: emergency_override → priority < TIME_OVERRIDE_MIN
        if has_emergency and priority >= cls.TIME_OVERRIDE_MIN:
            errors.append(
                f"{prefix}: emergency_override=True requires priority < {cls.TIME_OVERRIDE_MIN} "
                f"(Emergency tier), but got priority={priority} ({cls.get_tier_name(priority)}). "
                f"Emergency conditions must have highest priority to ensure safety."
            )

        # Rule 2: active_time_ranges → priority >= TIME_OVERRIDE_MIN
        if has_time_ranges and priority < cls.TIME_OVERRIDE_MIN:
            errors.append(
                f"{prefix}: time-based condition (active_time_ranges) requires "
                f"priority >= {cls.TIME_OVERRIDE_MIN} to avoid blocking emergency conditions, "
                f"but got priority={priority}. Time overrides must not prevent emergency execution."
            )

        # ═══════════════════════════════════════════════════════
        # SOFT RULES (Best Practices - Warnings Only)
        # ═══════════════════════════════════════════════════════

        # Suggestion 1: Time-based should use Time Override tier
        if has_time_ranges and not cls.is_time_override_tier(priority):
            warnings.append(
                f"{prefix}: time-based condition has priority={priority} "
                f"({cls.get_tier_name(priority)}). "
                f"Recommend Time Override tier ({cls.TIME_OVERRIDE_MIN}-{cls.TIME_OVERRIDE_MAX}) "
                f"for clarity and to ensure it blocks normal control."
            )

        # Suggestion 2: Emergency tier without emergency_override
        if cls.is_emergency_tier(priority) and not has_emergency:
            warnings.append(
                f"{prefix}: uses Emergency tier priority ({priority}) "
                f"but has no emergency_override=True. "
                f"Reserve Emergency tier (0-{cls.EMERGENCY_MAX}) for true emergencies only."
            )

        # Suggestion 3: Time Override tier without time ranges
        if cls.is_time_override_tier(priority) and not has_time_ranges:
            warnings.append(
                f"{prefix}: uses Time Override tier priority ({priority}) "
                f"but has no active_time_ranges. "
                f"This tier is reserved for time-based overrides."
            )

        # Suggestion 4: Priority outside defined ranges
        if not (
            cls.is_emergency_tier(priority)
            or cls.is_time_override_tier(priority)
            or cls.is_equipment_recovery_tier(priority)
            or cls.is_device_control_tier(priority)
            or cls.is_normal_control_tier(priority)
        ):
            warnings.append(
                f"{prefix}: priority={priority} is outside recommended tier ranges. "
                f"Consider using defined tiers for better organization. "
                f"See ControlPriority enum for tier definitions."
            )

        return errors, warnings
