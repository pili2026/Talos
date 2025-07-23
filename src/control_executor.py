import logging

from device_manager import AsyncDeviceManager
from generic_device import AsyncGenericModbusDevice
from model.control_model import ControlActionModel, ControlActionType


class ControlExecutor:
    def __init__(self, device_manager: AsyncDeviceManager):
        self.device_manager = device_manager
        self.logger = logging.getLogger("ControlExecutor")

    async def execute(self, action_list: list[ControlActionModel]):
        for action in action_list:
            device: AsyncGenericModbusDevice | None = self.device_manager.get_device_by_id(action.device_id)
            if not device:
                self.logger.warning(f"[SKIP] Device {action.device_id} not found.")
                continue

            try:
                # Special handler: reset
                if action.type == ControlActionType.RESET:
                    raw = 9 if action.value else 1
                    await device.write_value(action.target, raw)
                    self.logger.info(f"[RESET] {action.device_id} {action.target} => {raw}")
                    continue

                # Normal write path
                current_value: float | int = await device.read_value(action.target)
                if current_value == action.value:
                    self.logger.info(f"[SKIP] {action.device_id} {action.target} already set to {action.value}.")
                    continue

                await device.write_value(action.target, action.value)
                self.logger.info(f"[WRITE] {action.device_id} {action.target} => {action.value}")

            except Exception as e:
                self.logger.warning(f"[FAIL] Control failed for {action.device_id} {action.target}: {e}")
