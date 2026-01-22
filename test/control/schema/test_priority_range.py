import pytest
from pydantic import ValidationError

from core.model.enum.priority_range_enum import ControlPriority
from core.schema.control_condition_schema import ConditionSchema, ControlActionSchema, TimeRange


class TestControlPriorityTiers:
    """Tests for ControlPriority tier definitions"""

    def test_when_control_priority_defined_then_tier_boundaries_match_spec(self):
        """Test tier range boundaries"""
        assert ControlPriority.EMERGENCY_MIN == 0
        assert ControlPriority.EMERGENCY_MAX == 9

        assert ControlPriority.TIME_OVERRIDE_MIN == 10
        assert ControlPriority.TIME_OVERRIDE_MAX == 19

        assert ControlPriority.EQUIPMENT_RECOVERY_MIN == 20
        assert ControlPriority.EQUIPMENT_RECOVERY_MAX == 79

        assert ControlPriority.DEVICE_CONTROL_MIN == 80
        assert ControlPriority.DEVICE_CONTROL_MAX == 89

        assert ControlPriority.NORMAL_CONTROL_MIN == 90

    def test_when_priority_value_checked_then_correct_tier_is_identified(self):
        """Test tier check helper methods"""
        # Emergency tier
        assert ControlPriority.is_emergency_tier(0)
        assert ControlPriority.is_emergency_tier(5)
        assert ControlPriority.is_emergency_tier(9)
        assert not ControlPriority.is_emergency_tier(10)

        # Time Override tier
        assert ControlPriority.is_time_override_tier(10)
        assert ControlPriority.is_time_override_tier(15)
        assert ControlPriority.is_time_override_tier(19)
        assert not ControlPriority.is_time_override_tier(20)

        # Equipment Recovery tier (60 slots)
        assert ControlPriority.is_equipment_recovery_tier(20)
        assert ControlPriority.is_equipment_recovery_tier(50)
        assert ControlPriority.is_equipment_recovery_tier(79)
        assert not ControlPriority.is_equipment_recovery_tier(80)

        # Device Control tier
        assert ControlPriority.is_device_control_tier(80)
        assert ControlPriority.is_device_control_tier(89)
        assert not ControlPriority.is_device_control_tier(90)

        # Normal Control tier (unlimited)
        assert ControlPriority.is_normal_control_tier(90)
        assert ControlPriority.is_normal_control_tier(100)
        assert ControlPriority.is_normal_control_tier(999)

    def test_when_priority_value_given_then_correct_tier_name_is_returned(self):
        """Test retrieval of tier display names"""
        assert "Emergency" in ControlPriority.get_tier_name(0)
        assert "Time Override" in ControlPriority.get_tier_name(15)
        assert "Equipment Recovery" in ControlPriority.get_tier_name(50)
        assert "Device Control" in ControlPriority.get_tier_name(85)
        assert "Normal Control" in ControlPriority.get_tier_name(100)


class TestPriorityValidation:
    """Tests for priority validation logic"""

    def test_when_emergency_rule_uses_emergency_priority_then_no_validation_error(self):
        """Test a valid emergency configuration"""
        rule = ConditionSchema(
            name="Emergency",
            code="EMERGENCY",
            priority=0,
            actions=[
                ControlActionSchema(model="TECO_VFD", slave_id="1", type="set_frequency", emergency_override=True)
            ],
        )

        errors, warnings = ControlPriority.validate_safety_rules(rule)
        assert len(errors) == 0

    def test_when_emergency_rule_uses_high_priority_then_validation_error_is_returned(self):
        """Test emergency rule using a high priority (invalid)"""
        rule = ConditionSchema(
            name="Bad Emergency",
            code="BAD_EMERGENCY",
            priority=50,  # Too high
            actions=[
                ControlActionSchema(model="TECO_VFD", slave_id="1", type="set_frequency", emergency_override=True)
            ],
        )

        errors, warnings = ControlPriority.validate_safety_rules(rule)
        assert len(errors) == 1
        assert "requires priority < 10" in errors[0]

    def test_when_time_override_rule_has_valid_priority_and_time_range_then_no_validation_error(self):
        """Test a valid time override configuration"""
        rule = ConditionSchema(
            name="Morning Fixed",
            code="MORNING_FIXED",
            priority=10,
            active_time_ranges=[TimeRange(start="09:00", end="12:00")],
            actions=[],
        )

        errors, warnings = ControlPriority.validate_safety_rules(rule)
        assert len(errors) == 0

    def test_when_time_override_rule_uses_emergency_priority_then_validation_error_is_returned(self):
        """Test time override blocking emergency behavior (invalid)"""
        rule = ConditionSchema(
            name="Bad Time Override",
            code="BAD_TIME_OVERRIDE",
            priority=0,  # Emergency tier - blocks emergency!
            active_time_ranges=[TimeRange(start="09:00", end="12:00")],
            actions=[],
        )

        errors, warnings = ControlPriority.validate_safety_rules(rule)
        assert len(errors) == 1
        assert "requires priority >= 10" in errors[0]

    def test_when_time_override_rule_outside_recommended_tier_then_warning_is_returned(self):
        """Test time override outside the recommended tier (warning only)"""
        rule = ConditionSchema(
            name="Time Override High Priority",
            code="TIME_HIGH",
            priority=50,  # Valid but not recommended
            active_time_ranges=[TimeRange(start="09:00", end="12:00")],
            actions=[],
        )

        errors, warnings = ControlPriority.validate_safety_rules(rule)
        assert len(errors) == 0  # No hard errors
        assert len(warnings) == 1  # But produces a warning
        assert "Recommend Time Override tier" in warnings[0]

    def test_when_equipment_recovery_priorities_used_then_all_slots_are_available(self):
        """Test that the equipment recovery tier has sufficient capacity"""
        # Simulate 60 rules (priority range 20-79)
        rules = []
        for i in range(20, 80):
            rule = ConditionSchema(name=f"Recovery {i}", code=f"RECOVERY_{i}", priority=i, actions=[])
            errors, warnings = ControlPriority.validate_safety_rules(rule)
            assert len(errors) == 0  # All valid
            rules.append(rule)

        assert len(rules) == 60  # 60 slots available

    def test_when_normal_control_priority_used_then_no_upper_limit_is_enforced(self):
        """Test that the normal control tier has no upper limit"""
        for priority in [90, 100, 200, 999]:
            rule = ConditionSchema(name=f"Normal {priority}", code=f"NORMAL_{priority}", priority=priority, actions=[])
            errors, warnings = ControlPriority.validate_safety_rules(rule)
            assert len(errors) == 0
            assert ControlPriority.is_normal_control_tier(priority)

    def test_when_time_range_has_invalid_format_then_validation_error_is_raised(self):
        """Invalid time format must be rejected at schema level"""
        with pytest.raises(ValidationError):
            ConditionSchema(
                name="Invalid Format",
                code="INVALID_FORMAT",
                priority=10,
                active_time_ranges=[
                    TimeRange(start="09:00", end="12:00"),
                    TimeRange(start="25:00", end="26:00"),  # invalid
                    TimeRange(start="13:00", end="17:00"),
                ],
                actions=[],
            )
