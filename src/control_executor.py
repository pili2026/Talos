import logging

from device_manager import AsyncDeviceManager
from generic_device import AsyncGenericModbusDevice
from model.control_model import ControlActionModel


class ControlExecutor:
    def __init__(self, device_manager: AsyncDeviceManager):
        self.device_manager = device_manager
        self.logger = logging.getLogger("ControlExecutor")

    async def execute(self, action_list: list[ControlActionModel]):
        for action in action_list:
            device: AsyncGenericModbusDevice | None = self.device_manager.get_device_by_model_and_slave_id(
                action.model, action.slave_id
            )
            if not device:
                self.logger.warning(f"[SKIP] Device {action.model}_{action.slave_id} not found.")
                continue

            try:
                current_value: float | int = await device.read_value(action.target)
                if current_value == action.value:
                    self.logger.info(f"[SKIP] {device.model} {action.target} already set to {action.value}.")
                    continue

                await device.write_value(action.target, action.value)
                self.logger.info(f"[WRITE] {device.model} {action.target} => {action.value}")

            except Exception as e:
                self.logger.warning(f"[FAIL] Control failed for {device.model} {action.target}: {e}")
