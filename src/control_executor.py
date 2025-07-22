import logging

from control_evaluator import ControlAction
from device_manager import AsyncDeviceManager
from generic_device import AsyncGenericModbusDevice


class ControlExecutor:
    def __init__(self, device_manager: AsyncDeviceManager):
        self.device_manager = device_manager
        self.logger = logging.getLogger("ControlExecutor")

    async def execute(self, action_list: list[ControlAction]):
        for action in action_list:
            device: AsyncGenericModbusDevice | None = self.device_manager.get_device_by_id(action.device_id)
            if not device:
                self.logger.warning(f"[SKIP] Device {action.device_id} not found.")
                continue

            if action.type == "write_do":
                if action.target not in device.output_pins:
                    self.logger.warning(f"[SKIP] {action.device_id} has no DO {action.target}.")
                    continue
                await device.write_do(action.target, action.value)

            elif action.type == "set_frequency":
                if not hasattr(device, "set_frequency"):
                    self.logger.warning(f"[SKIP] {action.device_id} does not support frequency control.")
                    continue
                await device.set_frequency(action.value)
