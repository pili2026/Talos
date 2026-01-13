"""
Analyze current priority assignments
"""

import sys
from pathlib import Path
import yaml

from core.schema.control_config_schema import ControlConfig

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))


def analyze_config(config_path: Path):
    """Analyze priority assignments in config"""

    print(f"Analyzing: {config_path}")
    print("=" * 80)

    with open(config_path, "r", encoding="utf-8") as f:
        config_dict = yaml.safe_load(f)

    config = ControlConfig(**config_dict)

    # Collect all rules with their priorities
    rules = []

    for model_name, model_config in config.root.items():
        for control in model_config.default_controls:
            has_emergency = any(action.emergency_override for action in control.actions)

            has_time_ranges = control.active_time_ranges is not None

            rules.append(
                {
                    "location": f"{model_name}.default_controls",
                    "code": control.code,
                    "priority": control.priority,
                    "has_emergency": has_emergency,
                    "has_time_ranges": has_time_ranges,
                }
            )

        for instance_id, instance_config in model_config.instances.items():
            for control in instance_config.controls:
                has_emergency = any(action.emergency_override for action in control.actions)

                has_time_ranges = control.active_time_ranges is not None

                rules.append(
                    {
                        "location": f"{model_name}.instances[{instance_id}]",
                        "code": control.code,
                        "priority": control.priority,
                        "has_emergency": has_emergency,
                        "has_time_ranges": has_time_ranges,
                    }
                )

    # Group by priority
    by_priority = {}
    for rule in rules:
        p = rule["priority"]
        if p not in by_priority:
            by_priority[p] = []
        by_priority[p].append(rule)

    print(f"\nTotal rules: {len(rules)}")
    print(f"Unique priorities: {len(by_priority)}")
    print("\n" + "=" * 80)
    print("Rules by Priority:")
    print("=" * 80)

    for priority in sorted(by_priority.keys()):
        rule_list = by_priority[priority]
        print(f"\nPriority {priority}: {len(rule_list)} rules")

        for rule in rule_list:
            flags = []
            if rule["has_emergency"]:
                flags.append("EMERGENCY")
            if rule["has_time_ranges"]:
                flags.append("TIME_BASED")

            flag_str = f" [{', '.join(flags)}]" if flags else ""
            print(f"  • {rule['code']:<40} {flag_str}")

    # Check for issues
    print("\n" + "=" * 80)
    print("Potential Issues:")
    print("=" * 80)

    issues = []

    # Issue 1: Emergency not at priority=0
    for rule in rules:
        if rule["has_emergency"] and rule["priority"] != 0:
            issues.append(f"✗ {rule['code']}: emergency_override but priority={rule['priority']} (should be 0)")

    # Issue 2: Time-based at priority=0
    for rule in rules:
        if rule["has_time_ranges"] and rule["priority"] == 0:
            issues.append(f"✗ {rule['code']}: time-based but priority=0 (should be >= 10)")

    # Issue 3: Priority outside recommended ranges
    for rule in rules:
        p = rule["priority"]
        if not (p == 0 or (10 <= p <= 19) or (20 <= p <= 79) or (80 <= p <= 89) or p >= 90):
            issues.append(f"⚠ {rule['code']}: priority={p} outside recommended ranges")

    if issues:
        for issue in issues:
            print(f"  {issue}")
    else:
        print("  ✓ No issues found")

    return issues


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Analyze priority assignments")
    parser.add_argument("config", type=Path, help="Config file to analyze")

    args = parser.parse_args()

    if not args.config.exists():
        print(f"Error: Config file not found: {args.config}")
        sys.exit(1)

    issues = analyze_config(args.config)
    sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()
