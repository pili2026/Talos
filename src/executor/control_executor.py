import logging

from device_manager import AsyncDeviceManager
from generic_device import AsyncGenericModbusDevice
from model.control_model import ControlActionModel, ControlActionType


class ControlExecutor:
    def __init__(self, device_manager: AsyncDeviceManager):
        self.device_manager = device_manager
        self.logger = logging.getLogger(__class__.__name__)

    async def execute(self, action_list: list[ControlActionModel]):
        for action in action_list:
            device: AsyncGenericModbusDevice | None = self.device_manager.get_device_by_model_and_slave_id(
                action.model, action.slave_id
            )
            if not device:
                self.logger.warning(f"[SKIP] Device {action.model}_{action.slave_id} not found.")
                continue

            try:
                # --- TURN ON/OFF: check capability first, skip if unsupported ---
                if action.type in {ControlActionType.TURN_OFF, ControlActionType.TURN_ON}:
                    if not self._supports_on_off(device):
                        self.logger.info(f"[SKIP] {device.model} has no RW_ON_OFF capability. (Action: {action.type})")
                        continue

                    value = 0 if action.type == ControlActionType.TURN_OFF else 1
                    await device.write_on_off(value)
                    self.logger.info(f"[WRITE] {device.model} RW_ON_OFF => {value} ({action.type.name})")
                    continue

                # --- Other write-type actions: verify target/value/writability ---
                if not getattr(action, "target", None):
                    self.logger.warning(f"[SKIP] {device.model} missing target for action {action.type}.")
                    continue
                if not self._has_register(device, action.target):
                    self.logger.info(f"[SKIP] {device.model} no such register: {action.target}")
                    continue
                if not self._is_writable(device, action.target):
                    self.logger.info(f"[SKIP] {device.model} {action.target} is not writable.")
                    continue
                if getattr(action, "value", None) is None:
                    self.logger.warning(f"[SKIP] {device.model} {action.target} missing value for {action.type}.")
                    continue

                # Avoid redundant writes: read current value first
                current_value: float | int = await device.read_value(action.target)
                if current_value == action.value:
                    self.logger.info(f"[SKIP] {device.model} {action.target} already set to {action.value}.")
                    continue

                await device.write_value(
                    action.target, action.value
                )  # includes constraints validation and scaling internally
                self.logger.info(f"[WRITE] {device.model} {action.target} => {action.value}")

            except Exception as e:
                target_repr: str = getattr(action, "target", None) or "<RW_ON_OFF>"
                self.logger.warning(f"[FAIL] Control failed for {device.model} {target_repr}: {e}")

    # ---- helpers ----
    @staticmethod
    def _has_register(device: AsyncGenericModbusDevice, name: str) -> bool:
        return bool(name and name in device.register_map)

    @staticmethod
    def _is_writable(device: AsyncGenericModbusDevice, name: str) -> bool:
        cfg = device.register_map.get(name, {})
        return bool(cfg.get("writable", False))

    @staticmethod
    def _supports_on_off(device: AsyncGenericModbusDevice) -> bool:
        """Check by register_map whether RW_ON_OFF is supported; if not present, treat as unsupported."""
        cfg = device.register_map.get("RW_ON_OFF")
        return bool(cfg and cfg.get("writable", False))
