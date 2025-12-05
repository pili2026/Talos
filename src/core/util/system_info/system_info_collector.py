"""System Information Collector - Facade Pattern"""

from core.util.system_info.reboot_counter import RebootCounter
from core.util.system_info.ssh_port_detector import SSHPortDetector
from core.util.system_info.temperature_reader import TemperatureReader


class SystemInfoCollector:
    """
    System Information Collector (Unified Entry Point)

    Integrates:
    - RebootCounter: Reboot count
    - TemperatureReader: CPU temperature
    - SSHPortDetector: SSH port
    """

    def __init__(self, reboot_counter_file: str | None = None):
        self.reboot_counter = RebootCounter(reboot_counter_file)
        self.temperature_reader = TemperatureReader()
        self.ssh_port_detector = SSHPortDetector()

    def get_reboot_count(self) -> int:
        return self.reboot_counter.get_count()

    def increment_reboot_count(self):
        self.reboot_counter.increment()

    def reset_reboot_count(self):
        self.reboot_counter.reset()

    async def get_cpu_temperature(self) -> float:
        return await self.temperature_reader.read()

    async def get_ssh_port(self) -> int:
        return await self.ssh_port_detector.detect()

    def clear_ssh_port_cache(self):
        self.ssh_port_detector.clear_cache()

    @property
    def reboot_counter_file(self):
        return self.reboot_counter.counter_file
