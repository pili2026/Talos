import logging
from typing import Optional

from device.generic.generic_device import AsyncGenericModbusDevice
from device_manager import AsyncDeviceManager
from model.control_model import ControlActionModel, ControlActionType
from model.device_constant import REG_RW_ON_OFF

logger = logging.getLogger(__name__)

# Default target mapping (aligned with your config)
DEFAULT_TARGET_BY_ACTION: dict[ControlActionType, str] = {
    ControlActionType.SET_FREQUENCY: "RW_HZ",
    ControlActionType.ADJUST_FREQUENCY: "RW_HZ",
    ControlActionType.WRITE_DO: "RW_DO",
    ControlActionType.RESET: "RW_RESET",
}

# Numeric equality tolerance for value writes (0.0 = strict equality)
VALUE_TOLERANCE: float = 0.0


class ControlExecutor:
    def __init__(self, device_manager: AsyncDeviceManager):
        self.device_manager = device_manager
        self.logger = logging.getLogger(__class__.__name__)

    async def execute(self, action_list: list[ControlActionModel]):
        for action in action_list:
            # Basic context check
            if not action.model or not action.slave_id:
                self.logger.warning(
                    f"[EXEC] [SKIP] Missing model/slave_id in action: {action}.{self._get_reason_suffix(action)}"
                )
                continue

            device: Optional[AsyncGenericModbusDevice] = self.device_manager.get_device_by_model_and_slave_id(
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
                    if not getattr(device, "supports_on_off", None) or not device.supports_on_off():
                        self.logger.info(
                            f"[EXEC] [SKIP] {device.model} does not support ON/OFF.{self._get_reason_suffix(action)}"
                        )
                        continue

                    desired_state = 0 if action.type == ControlActionType.TURN_OFF else 1

                    # Read current state to avoid redundant writes (fallback to write if read fails)
                    current_state = None
                    try:
                        current_state = await device.read_value(REG_RW_ON_OFF)
                    except Exception as re:
                        self.logger.warning(
                            f"[EXEC] read {REG_RW_ON_OFF} failed on {device.model}: {re}. Will try to write anyway."
                        )

                    normalized_state = self._normalize_on_off_state(current_state)
                    if normalized_state is not None and normalized_state == desired_state:
                        self.logger.info(
                            f"[EXEC] [SKIP] {device.model} {REG_RW_ON_OFF} already {desired_state}.{self._get_reason_suffix(action)}"
                        )
                        continue

                    await device.write_on_off(desired_state)
                    self.logger.info(
                        f"[EXEC] [WRITE] {device.model} {REG_RW_ON_OFF} => {desired_state}.{self._get_reason_suffix(action)}"
                    )
                    continue

                # --- ADJUST_FREQUENCY (新增的處理邏輯) ---
                if action.type == ControlActionType.ADJUST_FREQUENCY:
                    target = action.target or DEFAULT_TARGET_BY_ACTION.get(action.type)
                    if not target:
                        self.logger.warning(
                            f"[EXEC] [SKIP] {device.model} missing target for ADJUST_FREQUENCY.{self._get_reason_suffix(action)}"
                        )
                        continue

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
                            f"[EXEC] [SKIP] {device.model} missing adjustment value for ADJUST_FREQUENCY.{self._get_reason_suffix(action)}"
                        )
                        continue

                    # 檢查調整量是否太小（避免無意義的微調）
                    if abs(float(action.value)) < VALUE_TOLERANCE:
                        self.logger.info(
                            f"[EXEC] [SKIP] {device.model} adjustment too small: {action.value}.{self._get_reason_suffix(action)}"
                        )
                        continue

                    # 讀取當前頻率
                    try:
                        current_freq = await device.read_value(target)
                        if current_freq is None:
                            self.logger.warning(
                                f"[EXEC] [SKIP] {device.model} cannot read current {target} for adjustment.{self._get_reason_suffix(action)}"
                            )
                            continue

                        # 計算新頻率：當前頻率 + 調整量
                        new_freq = float(current_freq) + float(action.value)

                        # 寫入新頻率（device 會處理範圍檢查和縮放）
                        await device.write_value(target, new_freq)
                        self.logger.info(
                            f"[EXEC] [ADJUST] {device.model} {target}: {current_freq} + {action.value} = {new_freq}.{self._get_reason_suffix(action)}"
                        )

                    except Exception as e:
                        self.logger.warning(
                            f"[EXEC] [FAIL] {device.model} ADJUST_FREQUENCY on {target}: {e}.{self._get_reason_suffix(action)}"
                        )
                    continue

                # --- Other actions (SET_FREQUENCY, WRITE_DO, RESET, etc.) ---
                target = action.target or DEFAULT_TARGET_BY_ACTION.get(action.type)
                if not target:
                    self.logger.warning(
                        f"[EXEC] [SKIP] {device.model} missing target for action {action.type}.{self._get_reason_suffix(action)}"
                    )
                    continue

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

            except Exception as e:
                target = action.target or (
                    REG_RW_ON_OFF
                    if action.type in {ControlActionType.TURN_ON, ControlActionType.TURN_OFF}
                    else "<unknown>"
                )
                self.logger.warning(
                    f"[EXEC] [FAIL] {action.model}_{action.slave_id} {target}: {e}.{self._get_reason_suffix(action)}"
                )

    @staticmethod
    def _has_register(device: AsyncGenericModbusDevice, name: str) -> bool:
        return bool(name and name in getattr(device, "register_map", {}))

    @staticmethod
    def _is_register_writable(device: AsyncGenericModbusDevice, name: str) -> bool:
        config = getattr(device, "register_map", {}).get(name, {})
        return bool(config.get("writable", False))

    @staticmethod
    def _normalize_on_off_state(value) -> Optional[int]:
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
    def _get_reason_suffix(action: ControlActionModel) -> str:
        """Return reason string prefixed with a space, if present."""
        return f" {action.reason}" if getattr(action, "reason", None) else ""
