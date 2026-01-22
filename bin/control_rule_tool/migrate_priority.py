"""
Priority Migration Script - Fixed for both config structures
"""

import sys
from pathlib import Path

import yaml


def migrate_priority(old_priority: int, rule_code: str, has_emergency: bool, has_time_ranges: bool) -> int:
    """Convert old priority to new tier-based priority"""

    # Priority 0: Emergency
    if has_emergency:
        return 0

    if "LOW_FREQ_PROTECT" in rule_code.upper():
        return 0

    # VFD Error/Recovery → 20-29
    if "ERROR_RESET" in rule_code.upper():
        return 20
    elif "ERROR_RECOVERY" in rule_code.upper() or "RECOVERY_ON" in rule_code.upper():
        return 21
    elif "AUTO_ON" in rule_code.upper() and "RECOVERY" not in rule_code.upper():
        return 22
    elif "FREQ_RECOVER" in rule_code.upper():
        return 23

    # Device Control → 80-89
    if "SHUTDOWN" in rule_code.upper():
        return 80
    if "TURN_ON" in rule_code.upper() and "AUTO" not in rule_code.upper() and "RECOVERY" not in rule_code.upper():
        return 81

    # Normal Control → 90-99
    if "SPEED_UP" in rule_code.upper() or "SPEEDUP" in rule_code.upper():
        return 90
    if "SLOW_DOWN" in rule_code.upper() or "SLOWDOWN" in rule_code.upper():
        return 91

    # Time-based → 10-19
    if has_time_ranges:
        return 10

    # Keep if already in valid range
    if (
        old_priority in [0]
        or (10 <= old_priority <= 19)
        or (20 <= old_priority <= 29)
        or (80 <= old_priority <= 89)
        or (old_priority >= 90)
    ):
        return old_priority
    else:
        return 90


def process_controls(controls: list, location: str) -> list:
    """Process a list of controls and return changes"""
    changes = []

    for control in controls:
        old_priority = control.get("priority", 0)
        rule_code = control.get("code", control.get("name", "UNKNOWN"))

        # Check for emergency_override
        has_emergency = any(action.get("emergency_override", False) for action in control.get("actions", []))

        # Check for active_time_ranges
        has_time_ranges = "active_time_ranges" in control and control["active_time_ranges"] is not None

        new_priority = migrate_priority(old_priority, rule_code, has_emergency, has_time_ranges)

        if new_priority != old_priority:
            changes.append(
                {
                    "location": location,
                    "rule": rule_code,
                    "old": old_priority,
                    "new": new_priority,
                    "reason": "emergency" if has_emergency else ("time_based" if has_time_ranges else "logic"),
                }
            )
            control["priority"] = new_priority

    return changes


def migrate_config_file(input_path: Path, output_path: Path, dry_run: bool = True):
    """Migrate priority values in control condition config"""

    print(f"Reading: {input_path}")

    with open(input_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    all_changes = []

    # Detect config structure
    has_root_key = "root" in config

    if has_root_key:
        print("Detected structure: config with 'root' key")
        models = config["root"]
    else:
        print("Detected structure: models at top level")
        # Filter out non-model keys
        models = {k: v for k, v in config.items() if k not in ["version"]}

    # Process all models
    for model_name, model_config in models.items():
        print(f"Processing model: {model_name}")

        # Process default_controls
        if "default_controls" in model_config:
            location = f"{model_name}.default_controls"
            changes = process_controls(model_config["default_controls"], location)
            all_changes.extend(changes)

        # Process instance controls
        if "instances" in model_config:
            for instance_id, instance_config in model_config["instances"].items():
                if "controls" in instance_config:
                    location = f"{model_name}.instances[{instance_id}]"
                    changes = process_controls(instance_config["controls"], location)
                    all_changes.extend(changes)

    # Print summary
    print(f"\n{'='*80}")
    print(f"Migration Summary: {len(all_changes)} changes")
    print(f"{'='*80}\n")

    if all_changes:
        # Group by priority tier
        tier_groups = {
            "Emergency (0-9)": [],
            "Time Override (10-19)": [],
            "Equipment Recovery (20-29)": [],
            "Device Control (80-89)": [],
            "Normal Control (90-99)": [],
        }

        for change in all_changes:
            new_p = change["new"]
            if new_p == 0:
                tier_groups["Emergency (0)"].append(change)
            elif 10 <= new_p <= 19:
                tier_groups["Time Override (10-19)"].append(change)
            elif 20 <= new_p <= 29:
                tier_groups["Equipment Recovery (20-29)"].append(change)
            elif 80 <= new_p <= 89:
                tier_groups["Device Control (80-89)"].append(change)
            else:
                tier_groups["Normal Control (90-99)"].append(change)

        for tier_name, tier_changes in tier_groups.items():
            if tier_changes:
                print(f"\n{tier_name}:")
                for change in tier_changes:
                    print(
                        f"  • {change['rule']:<45} "
                        f"{change['old']:>3} → {change['new']:<3} "
                        f"[{change['location']}]"
                    )
    else:
        print("No changes needed - configuration already up to date")

    # Write output
    if dry_run:
        print(f"\n{'='*80}")
        print("DRY RUN - No files written")
        print("Run with --apply to write changes")
        print(f"{'='*80}")
    else:
        print(f"\nWriting: {output_path}")
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        print("✓ Migration complete")

    return len(all_changes)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Migrate control condition priorities")
    parser.add_argument("input", type=Path, help="Input YAML file")
    parser.add_argument("output", type=Path, help="Output YAML file")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default: dry run)")

    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: Input file not found: {args.input}")
        sys.exit(1)

    changes = migrate_config_file(args.input, args.output, dry_run=not args.apply)

    if changes > 0:
        print(f"\n✓ Found {changes} changes")
        if not args.apply:
            print("  Run with --apply to write changes")
    else:
        print("\n✓ Configuration already up to date")


if __name__ == "__main__":
    main()
