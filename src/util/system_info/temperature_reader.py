"""
Temperature Reader

Responsibility: Read CPU temperature (supports Raspberry Pi)
"""

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger("TemperatureReader")


class TemperatureReader:
    """
    CPU Temperature Reader

    Supports:
    - Raspberry Pi thermal zone
    - vcgencmd command (fallback)
    """

    THERMAL_ZONE_PATH = Path("/sys/class/thermal/thermal_zone0/temp")

    async def read(self) -> float:
        """
        Read CPU temperature

        Returns:
            float: Temperature in Celsius, -1.0 if failed
        """
        # Method 1: thermal zone (preferred)
        temp = await self._read_from_thermal_zone()
        if temp != -1.0:
            return temp

        # Method 2: vcgencmd (fallback)
        temp = await self._read_from_vcgencmd()
        return temp

    async def _read_from_thermal_zone(self) -> float:
        """
        Read temperature from thermal zone

        Raspberry Pi standard method:
        Read from /sys/class/thermal/thermal_zone0/temp
        File content is in millidegree Celsius

        Returns:
            float: Temperature in Celsius, -1.0 if failed
        """
        try:
            if not self.THERMAL_ZONE_PATH.exists():
                logger.debug("Thermal zone not found")
                return -1.0

            # Read temperature value (in millidegree Celsius)
            temp_str = self.THERMAL_ZONE_PATH.read_text().strip()
            temp_millidegree = int(temp_str)

            # Convert to Celsius
            temp_celsius = temp_millidegree / 1000.0

            logger.debug(f"CPU temperature (thermal zone): {temp_celsius}°C")
            return round(temp_celsius, 1)

        except ValueError as e:
            logger.debug(f"Invalid temperature value: {e}")
            return -1.0
        except Exception as e:
            logger.debug(f"Failed to read from thermal zone: {e}")
            return -1.0

    async def _read_from_vcgencmd(self) -> float:
        """
        Read temperature using vcgencmd command (fallback method)

        Command: vcgencmd measure_temp
        Example output: temp=42.8'C

        Returns:
            float: Temperature in Celsius, -1.0 if failed
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "vcgencmd", "measure_temp", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.debug(f"vcgencmd failed with code {proc.returncode}")
                return -1.0

            # Parse output: temp=42.8'C
            output = stdout.decode().strip()
            if "temp=" in output:
                # Extract numeric part
                temp_str = output.split("=")[1].replace("'C", "").replace("°C", "")
                temp = float(temp_str)

                logger.debug(f"CPU temperature (vcgencmd): {temp}°C")
                return round(temp, 1)
            else:
                logger.debug(f"Unexpected vcgencmd output: {output}")
                return -1.0

        except FileNotFoundError:
            logger.debug("vcgencmd command not found")
            return -1.0
        except Exception as e:
            logger.debug(f"vcgencmd failed: {e}")
            return -1.0

    def __repr__(self) -> str:
        return f"TemperatureReader(thermal_zone={self.THERMAL_ZONE_PATH})"
