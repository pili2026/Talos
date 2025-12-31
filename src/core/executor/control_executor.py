import logging

from core.device.generic.generic_device import AsyncGenericModbusDevice
from core.model.device_constant import REG_RW_ON_OFF
from core.schema.control_condition_schema import ControlActionSchema, ControlActionType
from core.util.device_health_manager import DeviceHealthManager
from device_manager import AsyncDeviceManager

# Default target mapping (aligned with your config)
DEFAULT_TARGET_BY_ACTION: dict[ControlActionType, str] = {
    ControlActionType.SET_FREQUENCY: "RW_HZ",
    ControlActionType.ADJUST_FREQUENCY: "RW_HZ",
    ControlActionType.WRITE_DO: "RW_DO",
    ControlActionType.RESET: "RW_RESET",
}

# Numeric equality tolerance for value writes (0.0 = strict equality)
VALUE_TOLERANCE: float = 0.0


# TODO: Need Refactor and remove getattr
class ControlExecutor:
    def __init__(self, device_manager: AsyncDeviceManager, health_manager: DeviceHealthManager | None = None):
        self.device_manager = device_manager
        self.health_manager = health_manager
        self.logger = logging.getLogger(__class__.__name__)

    async def execute(self, action_list: list[ControlActionSchema]):
        # Track written targets with their priority and rule code
        # Key: "model_slave_target" → Value: (value, priority, rule_code)
        written_targets: dict[str, tuple[float | int, int, str]] = {}

        for action in action_list:
            device_id: str = f"{action.model}_{action.slave_id}"

            if self.health_manager and not self.health_manager.is_healthy(device_id):
                self.logger.debug(
                    f"[EXEC] [SKIP] {device_id} is offline, skip control action "
                    f"(type={action.type}, target={action.target}, value={action.value})"
                )
                continue

            # Basic context check
            if not action.model or not action.slave_id:
                self.logger.warning(
                    f"[EXEC] [SKIP] Missing model/slave_id in action: {action}.{self._get_reason_suffix(action)}"
                )
                continue

            device: AsyncGenericModbusDevice | None = self.device_manager.get_device_by_model_and_slave_id(
                action.model, action.slave_id
            )
            if not device:
                self.logger.warning(
                    f"[EXEC] [SKIP] Device {action.model}_{action.slave_id} not found.{self._get_reason_suffix(action)}"
                )
                continue

            try:
                # --- TURN ON/OFF ---
                if action.type in {ControlActionType.TURN_OFF, ControlActionType.TURN_ON}:
                    # Capability check
                    if not device.supports_on_off():
                        self.logger.info(
                            f"[EXEC] [SKIP] {device.model} does not support ON/OFF.{self._get_reason_suffix(action)}"
                        )
                        continue

                    desired_state = 0 if action.type == ControlActionType.TURN_OFF else 1
                    target = REG_RW_ON_OFF
                    device_key = f"{action.model}_{action.slave_id}"
                    target_key = f"{device_key}_{target}"

                    # Check priority protection
                    if self._is_protected_by_higher_priority(
                        target_key, desired_state, action.priority, written_targets, device_key, target, action
                    ):
                        continue

                    # Read current state to avoid redundant writes (fallback to write if read fails)
                    current_state = None
                    try:
                        current_state = await device.read_value(target)
                    except Exception as re:
                        self.logger.warning(
                            f"[EXEC] read {target} failed on {device.model}: {re}. Will try to write anyway."
                        )

                    normalized_state = self._normalize_on_off_state(current_state)
                    if normalized_state is not None and normalized_state == desired_state:
                        self.logger.info(
                            f"[EXEC] [SKIP] {device.model} {target} already {desired_state}.{self._get_reason_suffix(action)}"
                        )
                        continue

                    await device.write_on_off(desired_state)
                    self.logger.info(
                        f"[EXEC] [WRITE] {device.model} {target} => {desired_state}.{self._get_reason_suffix(action)}"
                    )

                    # Record written target
                    rule_code = self._extract_rule_code(action.reason)
                    written_targets[target_key] = (desired_state, action.priority or 999, rule_code)
                    continue

                # --- ADJUST_FREQUENCY ---
                if action.type == ControlActionType.ADJUST_FREQUENCY:
                    # Validate target
                    if not action.target:
                        self.logger.warning(
                            f"[EXEC] [SKIP] {device.model} missing target for ADJUST_FREQUENCY.{self._get_reason_suffix(action)}"
                        )
                        continue

                    target = action.target
                    device_key = f"{action.model}_{action.slave_id}"
                    target_key = f"{device_key}_{target}"

                    # Check register exists
                    if not self._has_register(device, target):
                        self.logger.info(
                            f"[EXEC] [SKIP] {device.model} no such register: {target}.{self._get_reason_suffix(action)}"
                        )
                        continue

                    # Check register is writable
                    if not self._is_register_writable(device, target):
                        self.logger.info(
                            f"[EXEC] [SKIP] {device.model} {target} is not writable.{self._get_reason_suffix(action)}"
                        )
                        continue

                    # Validate adjustment value
                    if action.value is None:
                        self.logger.warning(
                            f"[EXEC] [SKIP] {device.model} missing adjustment value for ADJUST_FREQUENCY.{self._get_reason_suffix(action)}"
                        )
                        continue

                    # Check if adjustment is too small
                    if abs(float(action.value)) <= VALUE_TOLERANCE:
                        self.logger.info(
                            f"[EXEC] [SKIP] {device.model} adjustment too small: {action.value}.{self._get_reason_suffix(action)}"
                        )
                        continue

                    # Read current frequency
                    current_freq = None
                    try:
                        current_freq = await device.read_value(target)
                    except Exception as read_error:
                        self.logger.warning(
                            f"[EXEC] [FAIL] {device.model} cannot read {target}: {read_error}.{self._get_reason_suffix(action)}"
                        )
                        continue

                    if current_freq is None:
                        self.logger.warning(
                            f"[EXEC] [SKIP] {device.model} {target} returned None value.{self._get_reason_suffix(action)}"
                        )
                        continue

                    # Compute new frequency
                    new_freq = float(current_freq) + float(action.value)

                    # Check priority protection
                    if self._is_protected_by_higher_priority(
                        target_key, new_freq, action.priority, written_targets, device_key, target, action
                    ):
                        continue

                    # Write new frequency
                    try:
                        await device.write_value(target, new_freq)
                        self.logger.info(
                            f"[EXEC] [ADJUST] {device.model} {target}: {current_freq} + {action.value} = {new_freq}.{self._get_reason_suffix(action)}"
                        )

                        # Record written target
                        rule_code = self._extract_rule_code(action.reason)
                        written_targets[target_key] = (new_freq, action.priority or 999, rule_code)

                    except Exception as write_error:
                        self.logger.warning(
                            f"[EXEC] [FAIL] {device.model} cannot write {target} to {new_freq}: {write_error}.{self._get_reason_suffix(action)}"
                        )

                    continue  # End of ADJUST_FREQUENCY block

                # --- Other actions (SET_FREQUENCY, WRITE_DO, RESET, etc.) ---
                target = action.target or DEFAULT_TARGET_BY_ACTION.get(action.type)
                if not target:
                    self.logger.warning(
                        f"[EXEC] [SKIP] {device.model} missing target for action {action.type}.{self._get_reason_suffix(action)}"
                    )
                    continue

                device_key = f"{action.model}_{action.slave_id}"
                target_key = f"{device_key}_{target}"

                if not self._has_register(device, target):
                    self.logger.info(
                        f"[EXEC] [SKIP] {device.model} no such register: {target}.{self._get_reason_suffix(action)}"
                    )
                    continue
                if not self._is_register_writable(device, target):
                    self.logger.info(
                        f"[EXEC] [SKIP] {device.model} {target} is not writable.{self._get_reason_suffix(action)}"
                    )
                    continue
                if action.value is None:
                    self.logger.warning(
                        f"[EXEC] [SKIP] {device.model} {target} missing value for {action.type}.{self._get_reason_suffix(action)}"
                    )
                    continue

                # Check priority protection
                if self._is_protected_by_higher_priority(
                    target_key, action.value, action.priority, written_targets, device_key, target, action
                ):
                    continue

                # Avoid redundant writes (with tolerance for numerics)
                current_value = None
                try:
                    current_value = await device.read_value(target)
                except Exception as re:
                    self.logger.warning(
                        f"[EXEC] read {target} failed on {device.model}: {re}. Will try to write anyway."
                    )

                if current_value is not None and self._is_value_equal_with_tolerance(current_value, action.value):
                    self.logger.info(
                        f"[EXEC] [SKIP] {device.model} {target} already {action.value}.{self._get_reason_suffix(action)}"
                    )
                    continue

                await device.write_value(target, action.value)  # device handles scaling/validation
                self.logger.info(
                    f"[EXEC] [WRITE] {device.model} {target} => {action.value}.{self._get_reason_suffix(action)}"
                )

                # Record written target
                rule_code = self._extract_rule_code(action.reason)
                written_targets[target_key] = (action.value, action.priority or 999, rule_code)

            except Exception as e:
                # Safe target retrieval for error logging
                try:
                    if "target" in locals():
                        target_name = target
                    elif action.target:
                        target_name = action.target
                    elif action.type in {ControlActionType.TURN_ON, ControlActionType.TURN_OFF}:
                        target_name = REG_RW_ON_OFF
                    else:
                        target_name = "<unknown>"
                except Exception:
                    target_name = "<unknown>"

                self.logger.warning(
                    f"[EXEC] [FAIL] {action.model}_{action.slave_id} {target_name}: {e}.{self._get_reason_suffix(action)}"
                )

    def _is_protected_by_higher_priority(
        self,
        target_key: str,
        new_value: float | int,
        current_priority: int | None,
        written_targets: dict[str, tuple[float | int, int, str]],
        device_key: str,
        target: str,
        action: ControlActionSchema,
    ) -> bool:
        """
        Check if the target is protected by a higher priority rule.
        Returns True if write should be skipped.
        """
        if target_key not in written_targets:
            return False

        prev_value, prev_priority, prev_rule = written_targets[target_key]
        action_priority = current_priority if current_priority is not None else 999

        # If previous priority is higher (smaller number), protect it
        if prev_priority < action_priority:
            self.logger.warning(
                f"[EXEC] [PROTECTED] {device_key} {target}: "
                f"already set to {prev_value} by higher priority rule {prev_rule} (p={prev_priority}), "
                f"skip current action (p={action_priority}).{self._get_reason_suffix(action)}"
            )
            return True

        # If we reach here, current priority is higher or equal, check for conflict
        if prev_value != new_value:
            self.logger.warning(
                f"[EXEC] [OVERWRITE] {device_key} {target}: "
                f"overwriting {prev_value} from {prev_rule} (p={prev_priority}) "
                f"with {new_value} (p={action_priority}).{self._get_reason_suffix(action)}"
            )

        return False

    @staticmethod
    def _extract_rule_code(reason: str | None) -> str:
        """Extract rule code from action reason string"""
        if not reason:
            return "<unknown>"
        # Reason format: "[RULE_CODE] Name | ..."
        import re

        match = re.search(r"\[([^\]]+)\]", reason)
        if match:
            return match.group(1)
        return "<unknown>"

    @staticmethod
    def _has_register(device: AsyncGenericModbusDevice, name: str) -> bool:
        return bool(name and name in getattr(device, "register_map", {}))

    @staticmethod
    def _is_register_writable(device: AsyncGenericModbusDevice, name: str) -> bool:
        config = getattr(device, "register_map", {}).get(name, {})
        return bool(config.get("writable", False))

    @staticmethod
    def _normalize_on_off_state(value) -> int | None:
        """Convert value to 0/1 if possible, else None."""
        try:
            return int(float(value))
        except Exception:
            return None

    @staticmethod
    def _is_value_equal_with_tolerance(a, b) -> bool:
        """Numeric compare with tolerance; fallback to == for non-numerics."""
        try:
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                return abs(float(a) - float(b)) <= VALUE_TOLERANCE
            return a == b
        except Exception:
            return False

    @staticmethod
    def _get_reason_suffix(action: ControlActionSchema) -> str:
        """Return reason string prefixed with a space, if present."""
        return f" {action.reason}" if getattr(action, "reason", None) else ""
