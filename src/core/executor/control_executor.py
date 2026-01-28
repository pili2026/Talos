import logging
import re
from dataclasses import dataclass
from typing import Literal

from core.device.generic.generic_device import AsyncGenericModbusDevice
from core.model.control_execution import WrittenTarget
from core.model.device_constant import DEFAULT_TARGET_BY_ACTION, REG_RW_ON_OFF, VALUE_TOLERANCE
from core.schema.control_condition_schema import ControlActionSchema, ControlActionType
from core.util.device_health_manager import DeviceHealthManager
from device_manager import AsyncDeviceManager

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ExecutionStats:
    total_actions: int = 0
    protected_writes: int = 0
    skipped_redundant: int = 0
    successful_writes: int = 0

    def reset(self, total_actions: int) -> None:
        self.total_actions = total_actions
        self.protected_writes = 0
        self.skipped_redundant = 0
        self.successful_writes = 0

    def summary_str(self) -> str:
        return (
            f"{self.successful_writes} writes, "
            f"{self.protected_writes} protected, "
            f"{self.skipped_redundant} redundant"
        )


class ControlExecutor:
    """
    Executes control actions with priority protection.

    Supported action types:
    - TURN_ON/TURN_OFF: Device power control
    - ADJUST_FREQUENCY: Incremental frequency adjustment
    - SET_FREQUENCY: Absolute frequency setting
    - WRITE_DO: Digital output control
    - RESET: Device reset

    Features:
    - Priority-based execution (lower number = higher priority)
    - Redundant write prevention
    - Device health checking
    - Comprehensive logging
    """

    def __init__(self, device_manager: AsyncDeviceManager, health_manager: DeviceHealthManager | None = None):
        self.device_manager = device_manager
        self.health_manager = health_manager
        self.logger = logging.getLogger(__class__.__name__)

        self._execution_stats = ExecutionStats()

    async def execute(self, action_list: list[ControlActionSchema]):
        """
        Execute a list of control actions with priority protection.

        Actions are processed in order, with priority protection preventing
        lower priority actions from overwriting higher priority writes.

        Args:
            action_list: List of actions to execute (should be pre-sorted by priority)
        """
        # Track written targets: "model_slave_target" → (value, priority, rule_code)
        written_targets: dict[str, WrittenTarget] = {}
        self._execution_stats.reset(total_actions=len(action_list))

        for action in action_list:
            # Pre-flight checks
            if not self._is_device_healthy(action):
                continue

            if not self._validate_action_fields(action):
                continue

            # Get device
            device: AsyncGenericModbusDevice | None = self.device_manager.get_device_by_model_and_slave_id(
                action.model, action.slave_id
            )
            if not device:
                self.logger.warning(f"[EXEC] [SKIP] Device {action.model}_{action.slave_id} not found")
                continue

            # Execute action by type
            try:
                await self._execute_action(action=action, device=device, written_targets=written_targets)
            except Exception as e:
                self.logger.warning(f"[EXEC] [FAIL] {action.model}_{action.slave_id}: {e}")

        self.logger.info(f"[EXEC] Summary: {self._execution_stats.summary_str()}")

    # ============================================================================
    # Main Action Router
    # ============================================================================

    async def _execute_action(
        self, action: ControlActionSchema, device: AsyncGenericModbusDevice, written_targets: dict[str, WrittenTarget]
    ):
        """Route action to appropriate handler based on type"""
        match action.type:
            case ControlActionType.TURN_ON | ControlActionType.TURN_OFF:
                await self._execute_turn_on_off(action, device, written_targets)

            case ControlActionType.ADJUST_FREQUENCY:
                await self._execute_adjust_frequency(action, device, written_targets)

            case ControlActionType.SET_FREQUENCY:
                await self._execute_set_value(action, device, written_targets)

            case ControlActionType.WRITE_DO:
                await self._execute_set_value(action, device, written_targets)

            case ControlActionType.RESET:
                await self._execute_set_value(action, device, written_targets)

            case _:
                self.logger.warning(f"[EXEC] [SKIP] Unknown action type: {action.type}")

    # ============================================================================
    # Action Type Handlers
    # ============================================================================

    async def _execute_turn_on_off(
        self, action: ControlActionSchema, device: AsyncGenericModbusDevice, written_targets: dict[str, WrittenTarget]
    ):
        """Handle TURN_ON/TURN_OFF actions"""
        # Capability check
        if not device.supports_on_off():
            self.logger.info(f"[EXEC] [SKIP] {device.model} does not support ON/OFF")
            return

        desired_state: Literal[0, 1] = 0 if action.type == ControlActionType.TURN_OFF else 1
        target = REG_RW_ON_OFF
        target_key: str = self._make_target_key(device, target)

        # Priority protection
        if self._is_protected(target_key, desired_state, action, written_targets):
            return

        # Read current state to avoid redundant writes
        current_state: int | None = await self._read_on_off_state(device, target)
        if current_state is not None and current_state == desired_state:
            self._execution_stats.skipped_redundant += 1
            self.logger.info(f"[EXEC] [SKIP] {device.model} {target} already {desired_state}")
            return

        # Write new state
        await device.write_on_off(desired_state)
        self.logger.info(f"[EXEC] [WRITE] {device.model} {target} => {desired_state}")
        self._execution_stats.successful_writes += 1

        # Record written target
        self._record_write(target_key, desired_state, action, written_targets)

    async def _execute_adjust_frequency(
        self, action: ControlActionSchema, device: AsyncGenericModbusDevice, written_targets: dict[str, WrittenTarget]
    ):
        """Handle ADJUST_FREQUENCY action (incremental change)"""
        # Validate target
        if not action.target:
            self.logger.warning(f"[EXEC] [SKIP] {device.model} missing target for ADJUST_FREQUENCY")
            return

        target = action.target
        target_key = self._make_target_key(device, target)

        # Validate register
        if not self._validate_register(device, target):
            return

        # Validate adjustment value
        if action.value is None:
            self.logger.warning(f"[EXEC] [SKIP] {device.model} missing adjustment value")
            return

        if abs(float(action.value)) <= VALUE_TOLERANCE:
            self.logger.info(f"[EXEC] [SKIP] {device.model} adjustment too small: {action.value}")
            return

        # Read current frequency
        current_freq = await self._read_value(device, target)
        if current_freq is None:
            self.logger.warning(f"[EXEC] [SKIP] {device.model} {target} returned None value")
            return

        # Compute new frequency
        new_freq = float(current_freq) + float(action.value)

        # Priority protection
        if self._is_protected(target_key, new_freq, action, written_targets):
            return

        # Write new frequency
        try:
            await device.write_value(target, new_freq)
            self._execution_stats.successful_writes += 1
            self.logger.info(
                f"[EXEC] [ADJUST] {device.model} {target}: " f"{current_freq} + {action.value} = {new_freq}"
            )

            # Record written target
            self._record_write(target_key, new_freq, action, written_targets)

        except Exception as write_error:
            self.logger.warning(f"[EXEC] [FAIL] {device.model} cannot write {target} to {new_freq}: " f"{write_error}")

    async def _execute_set_value(
        self, action: ControlActionSchema, device: AsyncGenericModbusDevice, written_targets: dict[str, WrittenTarget]
    ):
        """Handle SET_FREQUENCY, WRITE_DO, RESET actions (absolute value)"""
        # Determine target register
        target: str | None = action.target or DEFAULT_TARGET_BY_ACTION.get(action.type)
        if not target:
            self.logger.warning(f"[EXEC] [SKIP] {device.model} missing target for {action.type}")
            return

        target_key = self._make_target_key(device, target)

        # Validate register
        if not self._validate_register(device, target):
            return

        # Check value exists
        if action.value is None:
            self.logger.warning(f"[EXEC] [SKIP] {device.model} {target} missing value for {action.type}")
            return

        # Priority protection
        if self._is_protected(target_key, action.value, action, written_targets):
            return

        # Check redundancy
        current_value = await self._read_value(device, target)
        if current_value is not None and self._is_redundant_write(current_value, action.value):
            self._execution_stats.skipped_redundant += 1
            self.logger.info(f"[EXEC] [SKIP] {device.model} {target} already {action.value}")
            return

        # Write value
        await device.write_value(target, action.value)
        self._execution_stats.successful_writes += 1
        self.logger.info(f"[EXEC] [WRITE] {device.model} {target} => {action.value}")

        # Record written target
        self._record_write(target_key, action.value, action, written_targets)

    # ============================================================================
    # Helper Methods - Device Operations
    # ============================================================================

    def _validate_register(self, device: AsyncGenericModbusDevice, target: str) -> bool:
        """
        Validate that register exists and is writable.

        Args:
            device: Device to check
            target: Register name to validate

        Returns:
            True if register exists and is writable, False otherwise
        """
        # Check register exists
        if target not in device.register_map:
            self.logger.info(f"[EXEC] [SKIP] {device.model} no such register: {target}")
            return False

        # Check register is writable
        register_config = device.register_map[target]
        if not register_config.get("writable", False):
            self.logger.info(f"[EXEC] [SKIP] {device.model} {target} is not writable")
            return False

        return True

    async def _read_value(self, device: AsyncGenericModbusDevice, target: str) -> float | None:
        """
        Read current value from device register.

        Args:
            device: Device to read from
            target: Register name to read

        Returns:
            Current value or None if read failed
        """
        try:
            return await device.read_value(target)
        except Exception as e:
            self.logger.warning(f"[EXEC] read {target} failed on {device.model}: {e}. " f"Will try to write anyway.")
            return None

    async def _read_on_off_state(self, device: AsyncGenericModbusDevice, target: str) -> int | None:
        """
        Read current ON/OFF state from device.

        Args:
            device: Device to read from
            target: Register name to read (typically RW_ON_OFF)

        Returns:
            0 (OFF) or 1 (ON), or None if read failed
        """
        try:
            raw_value = await device.read_value(target)
            if raw_value is None:
                return None
            return int(float(raw_value))
        except Exception as e:
            self.logger.warning(f"[EXEC] read {target} failed on {device.model}: {e}. " f"Will try to write anyway.")
            return None

    # ============================================================================
    # Helper Methods - Priority Protection
    # ============================================================================

    def _is_protected(
        self,
        target_key: str,
        new_value: float | int,
        action: ControlActionSchema,
        written_targets: dict[str, WrittenTarget],
    ) -> bool:
        """
        Check if target is protected by a higher priority action.

        Args:
            target_key: Unique key for device+target combination
            new_value: Value to be written
            action: Current action being processed
            written_targets: Dictionary of already written targets

        Returns:
            True if write should be skipped (protected), False otherwise
        """
        if target_key not in written_targets:
            return False

        written_target: WrittenTarget = written_targets[target_key]
        action_priority: int = action.priority if action.priority is not None else 999

        # If previous priority is higher (smaller number), protect it
        if written_target.has_higher_priority_than(action_priority):
            self._execution_stats.protected_writes += 1
            self.logger.warning(
                f"[EXEC] [PROTECTED] {target_key}: "
                f"already set to {written_target.value} by higher priority rule {written_target.rule_code} "
                f"(p={written_target.priority}), skip current action (p={action_priority})"
            )
            return True

        # Current priority is higher or equal - check for conflict
        if written_target.conflicts_with(new_value):
            self.logger.warning(
                f"[EXEC] [OVERWRITE] {target_key}: "
                f"overwriting {written_target.value} from {written_target.rule_code} (p={written_target.priority}) "
                f"with {new_value} (p={action_priority})"
            )

        return False

    def _record_write(
        self,
        target_key: str,
        value: float | int,
        action: ControlActionSchema,
        written_targets: dict[str, WrittenTarget],
    ):
        """
        Record a successful write to prevent lower priority overwrites.

        Args:
            target_key: Unique key for device+target combination
            value: Value that was written
            action: Action that performed the write
            written_targets: Dictionary to update
        """
        rule_code: str = self._extract_rule_code(action.reason)
        priority: int = action.priority if action.priority is not None else 999
        written_targets[target_key] = WrittenTarget(value=value, priority=priority, rule_code=rule_code)

    # ============================================================================
    # Helper Methods - Validation & Utilities
    # ============================================================================

    def _is_device_healthy(self, action: ControlActionSchema) -> bool:
        """
        Check if device is healthy and online.

        Args:
            action: Action containing device information

        Returns:
            True if device is healthy or health manager not configured
        """
        if not self.health_manager:
            return True

        device_id = f"{action.model}_{action.slave_id}"
        if not self.health_manager.is_healthy(device_id):
            self.logger.debug(
                f"[EXEC] [SKIP] {device_id} is offline, skip control action "
                f"(type={action.type}, target={action.target}, value={action.value})"
            )
            return False

        return True

    def _validate_action_fields(self, action: ControlActionSchema) -> bool:
        """
        Validate that action has required fields.

        Args:
            action: Action to validate

        Returns:
            True if action has all required fields
        """
        if not action.model or not action.slave_id or not action.type:
            self.logger.warning("[EXEC] [SKIP] Invalid action: missing model/slave_id/type")
            return False
        return True

    @staticmethod
    def _make_target_key(device: AsyncGenericModbusDevice, target: str) -> str:
        """
        Create unique key for device+target combination.

        Args:
            device: Device object
            target: Register name

        Returns:
            Unique key string: "model_slave_id_target"
        """
        return f"{device.model}_{device.slave_id}_{target}"

    @staticmethod
    def _extract_rule_code(reason: str | None) -> str:
        """
        Extract rule code from action reason string.

        Reason format: "[RULE_CODE] Name | ..."

        Args:
            reason: Reason string from action

        Returns:
            Extracted rule code or "<unknown>"
        """
        if not reason:
            return "<unknown>"

        match = re.search(r"\[([^\]]+)\]", reason)
        return match.group(1) if match else "<unknown>"

    @staticmethod
    def _is_redundant_write(current: float | int, expected: float | int, tolerance: float = VALUE_TOLERANCE) -> bool:
        """
        Check if writing expected value would be redundant.

        A write is considered redundant if the current value already
        matches the expected value within the specified tolerance.
        This helps avoid unnecessary Modbus writes to devices.

        Args:
            current: Current value from device register
            expected: Expected/target value to write
            tolerance: Numeric comparison tolerance (default: 0.0 for strict equality)

        Returns:
            True if write would be redundant (values already match)
            False if write is needed (values differ)

        Examples:
            >>> # Exact match
            >>> _is_redundant_write(50.0, 50.0)
            True

            >>> # Within tolerance
            >>> _is_redundant_write(50.0, 50.05, tolerance=0.1)
            True

            >>> # Beyond tolerance
            >>> _is_redundant_write(50.0, 51.0, tolerance=0.1)
            False

            >>> # Non-numeric (exact equality)
            >>> _is_redundant_write("ON", "ON")
            True
        """
        try:
            if isinstance(current, (int, float)) and isinstance(expected, (int, float)):
                return abs(float(current) - float(expected)) <= tolerance
            return current == expected
        except Exception:
            return False
