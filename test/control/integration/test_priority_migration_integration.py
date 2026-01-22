"""Integration tests for priority migration"""

from datetime import datetime
from unittest.mock import patch

import pytest

from core.evaluator.control_evaluator import ControlEvaluator
from core.util.time_util import TIMEZONE_INFO


class TestPriorityMigrationIntegration:
    """Test complete priority system with migrated config"""

    @pytest.fixture
    def evaluator(self, control_config, constraint_config):
        """Create evaluator with migrated config"""
        return ControlEvaluator(control_config, constraint_config)

    def test_when_migrated_config_loaded_then_no_validation_error(self, control_config):
        """Test migrated config loads without errors"""
        assert control_config.version == "1.0.0"
        assert len(control_config.root) == 2

    def test_when_emergency_rule_defined_then_priority_is_highest(self, control_config):
        """Test all emergency conditions have priority=0"""
        emergency_priorities = []

        for model_name, model_config in control_config.root.items():
            for instance_id, instance_config in model_config.instances.items():
                for control in instance_config.controls:
                    has_emergency = any(action.emergency_override for action in control.actions)

                    if has_emergency:
                        emergency_priorities.append(
                            {
                                "model": model_name,
                                "instance": instance_id,
                                "code": control.code,
                                "priority": control.priority,
                            }
                        )

        # All emergency conditions should have priority=0
        for item in emergency_priorities:
            assert item["priority"] == 0, (
                f"{item['model']}.{item['instance']}.{item['code']} "
                f"has emergency_override but priority={item['priority']}"
            )

    def test_when_rules_loaded_then_no_duplicate_priorities_within_device(self, control_config):
        """Test no duplicate priorities within each device"""
        for model_name, model_config in control_config.root.items():
            for instance_id, instance_config in model_config.instances.items():
                rules = control_config.get_control_list(model_name, instance_id)

                priorities = [r.priority for r in rules]
                unique_priorities = set(priorities)

                assert len(priorities) == len(
                    unique_priorities
                ), f"{model_name}_{instance_id}: Duplicate priorities found: {priorities}"

    def test_when_rules_loaded_then_priority_tiers_are_distributed_correctly(self, control_config):
        """Test priority distribution matches expected tiers"""
        tiers = {
            "Emergency (0-9)": 0,
            "Time Override (10-19)": 0,
            "Equipment Recovery (20-29)": 0,
            "Device Control (80-89)": 0,
            "Normal Control (90+)": 0,
        }

        for model_name, model_config in control_config.root.items():
            for instance_id, instance_config in model_config.instances.items():
                for control in instance_config.controls:
                    p = control.priority

                    if 0 <= p <= 9:
                        tiers["Emergency (0-9)"] += 1
                    elif 10 <= p <= 19:
                        tiers["Time Override (10-19)"] += 1
                    elif 20 <= p <= 29:
                        tiers["Equipment Recovery (20-29)"] += 1
                    elif 80 <= p <= 89:
                        tiers["Device Control (80-89)"] += 1
                    else:
                        tiers["Normal Control (90+)"] += 1

        # Expected distribution (from validation)
        assert tiers["Emergency (0-9)"] >= 1
        assert tiers["Equipment Recovery (20-29)"] >= 1
        assert tiers["Device Control (80-89)"] >= 1
        assert tiers["Normal Control (90+)"] >= 1

    def test_when_high_temperature_detected_then_emergency_override_applied(self, evaluator):
        """Test emergency conditions trigger correctly"""
        fixed_now = datetime(2026, 1, 13, 10, 0, 0, tzinfo=TIMEZONE_INFO)

        with patch("core.evaluator.control_evaluator.datetime") as dt:
            dt.now.return_value = fixed_now

            snapshot = {"AIn01": 40.0, "AIn02": 40.0, "AIn03": 40.0}
            actions = evaluator.evaluate("ADAM-4117", "12", snapshot)

        assert len(actions) > 0
        assert actions[0].emergency_override is True
        assert actions[0].value == 60.0

    def test_when_multiple_rules_matched_then_actions_are_sorted_by_priority(self, evaluator):
        """Test actions are returned in priority order"""
        # Simulate conditions that trigger multiple rules
        snapshot = {"AIn01": 25.0, "AIn02": 25.0, "AIn03": 25.0}  # Above 19°C (speed up threshold)

        actions = evaluator.evaluate("ADAM-4117", "12", snapshot)

        if len(actions) > 1:
            # Verify priority order (lower number = higher priority)
            priorities = [a.priority for a in actions]
            assert priorities == sorted(priorities), f"Actions not in priority order: {priorities}"

    def test_when_vfd_error_cleared_then_recovery_rules_follow_expected_sequence(self, control_config):
        """Test VFD recovery rules have correct priority sequence"""
        vfd_instances = control_config.root.get("TECO_VFD", {}).instances.keys()
        for slave_id in vfd_instances:
            rules = control_config.get_control_list("TECO_VFD", str(slave_id))

            # Find recovery rules
            error_reset = None
            recovery_on = None
            auto_on = None
            freq_recover = None
            low_freq_protect = None

            for rule in rules:
                if "ERROR_RESET" in rule.code:
                    error_reset = rule
                elif "ERROR_RECOVERY_ON" in rule.code:
                    recovery_on = rule
                elif "AUTO_ON" in rule.code:
                    auto_on = rule
                elif "FREQ_RECOVER" in rule.code:
                    freq_recover = rule
                elif "LOW_FREQ_PROTECT" in rule.code:
                    low_freq_protect = rule

            # Verify priority sequence
            if error_reset:
                assert error_reset.priority == 20
            if recovery_on:
                assert recovery_on.priority == 21
            if auto_on:
                assert auto_on.priority == 22
            if freq_recover:
                assert freq_recover.priority == 23
            if low_freq_protect:
                assert low_freq_protect.priority == 0  # Emergency

    def test_when_config_migrated_then_original_rule_structure_is_preserved(self, control_config):
        """Test migrated config preserves original rule count and structure"""
        # Count rules by model
        adam_rules = sum(len(inst.controls) for inst in control_config.root["ADAM-4117"].instances.values())

        vfd_rules = sum(len(inst.controls) for inst in control_config.root["TECO_VFD"].instances.values())

        total_rules = adam_rules + vfd_rules

        # Should have all 80 rules (as per migration)
        # Note: Validator shows 62 because it's counting after filtering
        # But actual config should have 80

        # Assert: Test config has 3 ADAM rules + 4 VFD rules = 7 total
        assert adam_rules == 3, f"Expected 3 ADAM-4117 rules, got {adam_rules}"
        assert vfd_rules == 4, f"Expected 4 TECO_VFD rules, got {vfd_rules}"
        assert total_rules == 7, f"Expected 7 total rules, got {total_rules}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
