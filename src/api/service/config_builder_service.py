"""
Config Builder Service

Business logic for the Config Builder API:
- Reading device / driver configuration from YAML files
- Validating control and alert configs with existing Pydantic schemas
- Generating YAML output from structured form data
- Generating Mermaid flowchart diagrams from config YAML
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError as PydanticValidationError

from core.model.control_composite import CompositeNode
from core.schema.alert_config_schema import AlertConfig
from core.schema.alert_schema import AlertConditionModel
from core.schema.control_config_schema import ControlConfig
from core.schema.control_condition_schema import ConditionSchema
from core.schema.driver_schema import DriverConfig
from core.schema.modbus_device_schema import ModbusDeviceFileConfig

logger = logging.getLogger("ConfigBuilderService")


class ConfigBuilderService:
    """
    Reads configuration files (YAML) and provides:
    - Device / pin listing (from modbus_device.yml + driver files)
    - Control/alert YAML validation
    - Control/alert YAML generation
    - Mermaid diagram generation
    """

    def __init__(self, config_dir: Path | str):
        self.config_dir = Path(config_dir)
        self.modbus_device_path = self.config_dir / "modbus_device.yml"

    # =========================================================================
    # Internal helpers
    # =========================================================================

    def _load_raw_yaml(self, path: Path) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _load_driver(self, model_file: str) -> DriverConfig | None:
        """Load and validate a driver YAML file relative to config_dir."""
        driver_path = self.config_dir / model_file
        if not driver_path.exists():
            logger.warning(f"[ConfigBuilder] Driver file not found: {driver_path}")
            return None
        try:
            raw = self._load_raw_yaml(driver_path)
            return DriverConfig.model_validate(raw)
        except Exception as exc:
            logger.warning(f"[ConfigBuilder] Failed to parse driver {model_file}: {exc}")
            return None

    def _load_modbus_file_config(self) -> ModbusDeviceFileConfig | None:
        if not self.modbus_device_path.exists():
            logger.warning(f"[ConfigBuilder] modbus_device.yml not found at {self.modbus_device_path}")
            return None
        try:
            raw = self._load_raw_yaml(self.modbus_device_path)
            return ModbusDeviceFileConfig.model_validate(raw)
        except Exception as exc:
            logger.warning(f"[ConfigBuilder] Failed to parse modbus_device.yml: {exc}")
            return None

    @staticmethod
    def _wrap_alert_yaml(raw: dict) -> dict:
        """
        AlertConfig expects {'version': ..., 'root': {model: ...}}.
        Live YAML files use the flat format (model keys at top level).
        """
        version = raw.get("version", "1.0.0")
        root_dict = {k: v for k, v in raw.items() if k != "version"}
        return {"version": version, "root": root_dict}

    # =========================================================================
    # Device / Pin Listing
    # =========================================================================

    def get_devices(self) -> list[dict[str, Any]]:
        """
        Return all devices defined in modbus_device.yml with their pin names.

        Returns a list of dicts: {model, slave_id, type, pins}.
        """
        file_config = self._load_modbus_file_config()
        if not file_config:
            return []

        result: list[dict[str, Any]] = []
        for device in file_config.device_list:
            pins: list[str] = []
            if device.model_file:
                driver = self._load_driver(device.model_file)
                if driver:
                    pins = list(driver.register_map.keys())

            result.append(
                {
                    "model": device.model,
                    "slave_id": device.slave_id,
                    "type": device.type,
                    "pins": pins,
                }
            )

        return result

    def get_device_pins(self, model: str) -> dict[str, Any] | None:
        """
        Return readable/writable pin details for the first device matching *model*.

        Returns None if the model is not found.
        """
        file_config = self._load_modbus_file_config()
        if not file_config:
            return None

        model_file: str | None = None
        for device in file_config.device_list:
            if device.model == model:
                model_file = device.model_file
                break

        if not model_file:
            logger.info(f"[ConfigBuilder] Model '{model}' not found in modbus_device.yml")
            return None

        driver = self._load_driver(model_file)
        if not driver:
            return None

        readable: list[dict[str, Any]] = []
        writable: list[dict[str, Any]] = []

        for pin_name, pin_def in driver.register_map.items():
            info: dict[str, Any] = {
                "name": pin_name,
                "readable": pin_def.readable,
                "writable": pin_def.writable,
                "type": getattr(pin_def, "type", None),
                "unit": getattr(pin_def, "unit", None),
                "description": getattr(pin_def, "description", None),
            }
            if pin_def.readable:
                readable.append(info)
            if pin_def.writable:
                writable.append(info)

        return {
            "model": model,
            "readable_pins": readable,
            "writable_pins": writable,
        }

    # =========================================================================
    # Validation
    # =========================================================================

    def validate_control_config(self, yaml_content: str) -> dict[str, Any]:
        """
        Validate a control_condition YAML string.

        ControlConfig.normalize_structure() auto-wraps the flat YAML under 'root'.

        Returns {'valid': bool, 'errors': [{'location': str, 'message': str}]}.
        """
        try:
            raw = yaml.safe_load(yaml_content)
        except yaml.YAMLError as exc:
            return {
                "valid": False,
                "errors": [{"location": "yaml", "message": f"YAML parse error: {exc}"}],
            }

        errors: list[dict[str, str]] = []
        try:
            ControlConfig.model_validate(raw)
        except PydanticValidationError as exc:
            for err in exc.errors():
                location = " -> ".join(str(loc) for loc in err["loc"])
                errors.append({"location": location, "message": err["msg"]})
        except ValueError as exc:
            # ControlConfig raises ValueError for hard validation failures
            for line in str(exc).splitlines():
                line = line.strip()
                if line:
                    errors.append({"location": "root", "message": line})

        return {"valid": len(errors) == 0, "errors": errors}

    def validate_alert_config(self, yaml_content: str) -> dict[str, Any]:
        """
        Validate an alert_condition YAML string.

        Manually wraps flat YAML under 'root' (same as alert_factory._parse_alert_config_dict).

        Returns {'valid': bool, 'errors': [{'location': str, 'message': str}]}.
        """
        try:
            raw = yaml.safe_load(yaml_content)
        except yaml.YAMLError as exc:
            return {
                "valid": False,
                "errors": [{"location": "yaml", "message": f"YAML parse error: {exc}"}],
            }

        errors: list[dict[str, str]] = []
        try:
            wrapped = self._wrap_alert_yaml(raw)
            AlertConfig.model_validate(wrapped)
        except PydanticValidationError as exc:
            for err in exc.errors():
                location = " -> ".join(str(loc) for loc in err["loc"])
                errors.append({"location": location, "message": err["msg"]})
        except ValueError as exc:
            errors.append({"location": "root", "message": str(exc)})

        return {"valid": len(errors) == 0, "errors": errors}

    # =========================================================================
    # YAML Generation
    # =========================================================================

    def generate_control_yaml(
        self,
        version: str,
        model: str,
        slave_id: str,
        use_default_controls: bool,
        default_controls: list[dict],
        controls: list[dict],
    ) -> str:
        """
        Produce a control_condition YAML string in the flat format:

            version: "2.0.0"
            TECO_VFD:
              default_controls: []
              instances:
                "1":
                  use_default_controls: false
                  controls: [...]
        """
        data: dict[str, Any] = {
            "version": version,
            model: {
                "default_controls": default_controls,
                "instances": {
                    slave_id: {
                        "use_default_controls": use_default_controls,
                        "controls": controls,
                    }
                },
            },
        }
        return yaml.dump(
            data,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            indent=2,
            width=120,
        )

    def generate_alert_yaml(
        self,
        version: str,
        model: str,
        slave_id: str,
        use_default_alerts: bool,
        default_alerts: list[dict],
        alerts: list[dict],
    ) -> str:
        """
        Produce an alert_condition YAML string in the flat format:

            version: "1.1.0"
            TECO_VFD:
              default_alerts: []
              instances:
                "1":
                  use_default_alerts: false
                  alerts: [...]
        """
        data: dict[str, Any] = {
            "version": version,
            model: {
                "default_alerts": default_alerts,
                "instances": {
                    slave_id: {
                        "use_default_alerts": use_default_alerts,
                        "alerts": alerts,
                    }
                },
            },
        }
        return yaml.dump(
            data,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            indent=2,
            width=120,
        )

    # =========================================================================
    # Diagram Generation
    # =========================================================================

    def generate_control_diagram(self, yaml_content: str) -> str:
        """
        Parse a control_condition YAML and return a Mermaid flowchart string.

        Each model/instance becomes a subgraph; each control rule is rendered
        with its composite condition tree, policy, and actions.
        """
        try:
            raw = yaml.safe_load(yaml_content)
            config = ControlConfig.model_validate(raw)
        except Exception as exc:
            safe_msg = str(exc).replace('"', "'")
            return f'flowchart TD\n    ERR["Parse Error: {safe_msg}"]'

        counter: list[int] = [0]

        def nid(prefix: str = "N") -> str:
            counter[0] += 1
            return f"{prefix}{counter[0]}"

        def safe(text: str) -> str:
            return text.replace('"', "'").replace("\n", "<br/>")

        def render_node(node: CompositeNode, parent_id: str, lines: list[str], indent: str) -> None:
            """Recursively render a CompositeNode into Mermaid lines."""
            branch_count = sum(x is not None for x in (node.all, node.any, node.not_))

            if branch_count > 0:
                # Group node (all / any / not)
                if node.all is not None:
                    gid = nid("G")
                    lines.append(f'{indent}{gid}(["ALL of the following"])')
                    lines.append(f"{indent}{parent_id} --> {gid}")
                    for child in node.all:
                        render_node(child, gid, lines, indent)

                elif node.any is not None:
                    gid = nid("G")
                    lines.append(f'{indent}{gid}(["ANY of the following"])')
                    lines.append(f"{indent}{parent_id} --> {gid}")
                    for child in node.any:
                        render_node(child, gid, lines, indent)

                elif node.not_ is not None:
                    gid = nid("G")
                    lines.append(f'{indent}{gid}(["NOT"])')
                    lines.append(f"{indent}{parent_id} --> {gid}")
                    render_node(node.not_, gid, lines, indent)

            elif node.type is not None:
                # Leaf node
                parts: list[str] = [f"type: {node.type.value}"]
                if node.operator:
                    parts.append(f"op: {node.operator.value}")
                if node.threshold is not None:
                    parts.append(f"threshold: {node.threshold}")
                if node.min is not None and node.max is not None:
                    parts.append(f"between: [{node.min}, {node.max}]")

                if node.sources:
                    src_strs = []
                    for src in node.sources:
                        pins_str = ", ".join(src.pins)
                        agg = src.get_effective_aggregation()
                        agg_str = f" [{agg.value}]" if agg else ""
                        src_strs.append(f"{src.device}/{src.slave_id}: {pins_str}{agg_str}")
                    parts.append("sources: " + " | ".join(src_strs))

                if node.sources_id:
                    parts.append(f"id: {node.sources_id}")

                lid = nid("L")
                label = safe("<br/>".join(parts))
                lines.append(f'{indent}{lid}["{label}"]')
                lines.append(f"{indent}{parent_id} --> {lid}")

        lines: list[str] = ["flowchart TD"]

        for model_name, model_cfg in config.root.items():
            for instance_id, instance_cfg in model_cfg.instances.items():
                if not instance_cfg.controls:
                    continue

                sg_id = nid("SG")
                lines.append(f'    subgraph {sg_id}["{safe(model_name)} / Slave {instance_id}"]')

                for ctrl in instance_cfg.controls:
                    rule_id = nid("R")
                    rule_label = safe(
                        f"Rule: {ctrl.name}<br/>code={ctrl.code}<br/>priority={ctrl.priority}"
                        + (" [BLOCKING]" if ctrl.blocking else "")
                    )
                    lines.append(f'        {rule_id}["{rule_label}"]')

                    # Composite condition tree
                    if ctrl.composite:
                        render_node(ctrl.composite, rule_id, lines, "        ")

                    # Policy
                    if ctrl.policy and ctrl.policy.type:
                        pid = nid("P")
                        policy_parts = [f"Policy: {ctrl.policy.type.value}"]
                        if ctrl.policy.input_source:
                            policy_parts.append(f"input: {ctrl.policy.input_source}")
                        lines.append(f'        {pid}["{safe("<br/>".join(policy_parts))}"]')
                        lines.append(f"        {rule_id} --> {pid}")

                    # Actions
                    for action in ctrl.actions:
                        if action.type is None:
                            continue
                        aid = nid("A")
                        action_parts = [f"Action: {action.type.value}"]
                        if action.target:
                            action_parts.append(f"target: {action.target}")
                        if action.value is not None:
                            action_parts.append(f"value: {action.value}")
                        if action.model and action.slave_id:
                            action_parts.append(f"→ {action.model}/{action.slave_id}")
                        lines.append(f'        {aid}["{safe("<br/>".join(action_parts))}"]')
                        lines.append(f"        {rule_id} -->|trigger| {aid}")

                lines.append("    end")

        return "\n".join(lines)

    def generate_alert_diagram(self, yaml_content: str) -> str:
        """
        Parse an alert_condition YAML and return a Mermaid flowchart string.

        Each model/instance becomes a subgraph; each alert is rendered with its
        type, condition, sources, and severity.
        """
        try:
            raw = yaml.safe_load(yaml_content)
            wrapped = self._wrap_alert_yaml(raw)
            config = AlertConfig.model_validate(wrapped)
        except Exception as exc:
            safe_msg = str(exc).replace('"', "'")
            return f'flowchart TD\n    ERR["Parse Error: {safe_msg}"]'

        counter: list[int] = [0]

        def nid(prefix: str = "N") -> str:
            counter[0] += 1
            return f"{prefix}{counter[0]}"

        def safe(text: str) -> str:
            return text.replace('"', "'").replace("\n", "<br/>")

        def alert_condition_label(alert: AlertConditionModel) -> str:
            parts: list[str] = [f"type: {alert.type.value}"]
            if hasattr(alert, "condition"):
                parts.append(f"condition: {alert.condition.value}")
            if hasattr(alert, "threshold"):
                parts.append(f"threshold: {alert.threshold}")
            if hasattr(alert, "expected_state"):
                parts.append(f"expected_state: {alert.expected_state}")
            if hasattr(alert, "active_hours"):
                ah = alert.active_hours
                parts.append(f"active_hours: {ah.start}~{ah.end}")
            parts.append(f"sources: {', '.join(alert.sources)}")
            return "<br/>".join(parts)

        lines: list[str] = ["flowchart TD"]

        for model_name, model_cfg in config.root.items():
            for instance_id, instance_cfg in model_cfg.instances.items():
                if not instance_cfg.alerts:
                    continue

                sg_id = nid("SG")
                lines.append(f'    subgraph {sg_id}["{safe(model_name)} / Slave {instance_id}"]')

                for alert in instance_cfg.alerts:
                    alert_id = nid("AL")
                    alert_label = safe(
                        f"Alert: {alert.name}<br/>code={alert.code}<br/>severity={alert.severity.value}"
                    )
                    lines.append(f'        {alert_id}["{alert_label}"]')

                    cond_id = nid("C")
                    cond_label = safe(alert_condition_label(alert))
                    lines.append(f'        {cond_id}["{cond_label}"]')
                    lines.append(f"        {alert_id} --> {cond_id}")

                lines.append("    end")

        return "\n".join(lines)
