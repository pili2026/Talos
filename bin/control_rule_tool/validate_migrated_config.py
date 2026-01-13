"""Validate migrated configuration"""

import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # control_rule_tool -> bin -> talos
SRC_DIR = PROJECT_ROOT / "src"

if not SRC_DIR.exists():
    raise RuntimeError(f"Cannot find src directory at: {SRC_DIR}")

sys.path.insert(0, str(SRC_DIR))

from core.schema.control_config_schema import ControlConfig  # noqa: E402


def main():
    config_path = PROJECT_ROOT / "res" / "control_condition_migrated.yml"

    if len(sys.argv) > 1:
        config_path = Path(sys.argv[1])

    print(f"Validating: {config_path}")
    print("=" * 80)

    try:
        # Load YAML
        with open(config_path, "r", encoding="utf-8") as f:
            config_dict = yaml.safe_load(f)

        # Try to load config
        # If your schema expects no 'root' key, this should work directly
        config = ControlConfig(**config_dict)

        print("✓ Configuration loaded successfully")
        print(f"  Version: {config.version}")

        # Count rules by tier
        tiers = {
            "Emergency (0-9)": 0,
            "Time Override (10-19)": 0,
            "Equipment Recovery (20-29)": 0,
            "Device Control (80-89)": 0,
            "Normal Control (90+)": 0,
        }

        total_rules = 0

        # Access models - adjust based on actual schema structure
        models = config.root if hasattr(config, "root") else config_dict

        for model_name, model_config in models.items():
            if model_name == "version":
                continue

            # Handle both dict and object access
            instances = model_config.get("instances", {}) if isinstance(model_config, dict) else model_config.instances

            for instance_id, instance_config in instances.items():
                controls = (
                    instance_config.get("controls", [])
                    if isinstance(instance_config, dict)
                    else instance_config.controls
                )

                for control in controls:
                    total_rules += 1
                    p = control.get("priority") if isinstance(control, dict) else control.priority

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

        print(f"\n{'=' * 80}")
        print("Priority Distribution:")
        print("=" * 80)
        for tier, count in tiers.items():
            print(f"  {tier:<35} {count:>3} rules")

        print(f"\n  Total: {total_rules} rules")
        print(f"\n{'=' * 80}")
        print("✓ All validation checks passed")

        return True

    except Exception as e:
        print(f"\n{'=' * 80}")
        print("✗ Validation failed:")
        print(f"  {e}")
        import traceback

        traceback.print_exc()
        print("=" * 80)
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
