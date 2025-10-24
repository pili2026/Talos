import logging

from pymodbus.client import AsyncModbusSerialClient

from model.device_constant import DEFAULT_MISSING_VALUE
from model.enum.register_type_enum import RegisterType

logger = logging.getLogger("ModbusBus")


class ModbusBus:
    def __init__(self, client: AsyncModbusSerialClient, slave_id: int, register_type: str):
        """
        Initialize ModbusBus.

        Args:
            client: pymodbus AsyncModbusSerialClient
            slave_id: Modbus slave address
            register_type: "holding", "input", "coil", or "discrete_input"
        """
        self.client = client
        self.slave_id = int(slave_id)
        self.register_type = register_type

    async def ensure_connected(self) -> bool:
        """Ensure the Modbus connection is established."""
        if self.client.connected:
            return True

        is_ok: bool = await self.client.connect()
        if not is_ok:
            logger.error(f"[Bus] connect failed (slave={self.slave_id})")

        return is_ok

    # ==================== Original register methods ====================

    async def read_u16(self, offset: int) -> int:
        """Read a single 16-bit register."""
        regs = await self.read_regs(offset, 1)
        return int(regs[0])

    async def read_regs(self, offset: int, count: int) -> list[int]:
        """Read multiple registers."""
        if not self.client.connected and not await self.client.connect():
            logger.error(f"[Bus] connect failed (slave={self.slave_id}), return missing values")
            return [DEFAULT_MISSING_VALUE] * count

        if self.register_type == "holding":
            resp = await self.client.read_holding_registers(address=offset, count=count, slave=self.slave_id)
        elif self.register_type == "input":
            resp = await self.client.read_input_registers(address=offset, count=count, slave=self.slave_id)
        else:
            logger.error(f"[Bus] Unsupported register type: {self.register_type}")
            return [DEFAULT_MISSING_VALUE] * count

        if resp.isError():
            logger.warning(f"[Bus] Modbus error response: {resp}")
            return [DEFAULT_MISSING_VALUE] * count
        return resp.registers

    async def write_u16(self, offset: int, value: int):
        """Write a single 16-bit register."""
        await self.client.write_register(address=offset, value=value, slave=self.slave_id)

    # ==================== New Coil methods ====================

    async def read_coil(self, offset: int) -> int:
        """
        Read a single Coil (Function Code 01).

        Args:
            offset: Coil address (0-based)

        Returns:
            int: Coil state (1=ON, 0=OFF, -1=READ_FAILED)
        """
        coils = await self.read_coils(offset, 1)
        return coils[0]

    async def read_coils(self, offset: int, count: int) -> list[int]:
        """
        Read multiple Coils (Function Code 01).

        Args:
            offset: Starting coil address (0-based)
            count: Number of coils to read

        Returns:
            List[int]: Coil states (1=ON, 0=OFF, -1=READ_FAILED)
        """
        if not self.client.connected and not await self.client.connect():
            logger.error(f"[Bus] connect failed (slave={self.slave_id}), return missing values")
            return [DEFAULT_MISSING_VALUE] * count

        try:
            resp = await self.client.read_coils(address=offset, count=count, slave=self.slave_id)

            if resp.isError():
                logger.warning(f"[Bus] Coil read error: {resp}")
                return [DEFAULT_MISSING_VALUE] * count

            # Convert bool to int: True→1, False→0
            return [1 if bit else 0 for bit in resp.bits[:count]]

        except Exception as e:
            logger.error(f"[Bus] Exception reading coils: {e}")
            return [DEFAULT_MISSING_VALUE] * count

    async def write_coil(self, offset: int, value: bool) -> bool:
        """
        Write a single Coil (Function Code 05).

        Args:
            offset: Coil address (0-based)
            value: Coil state (True=ON, False=OFF)

        Returns:
            bool: Write success (True=success, False=failed)
        """
        if not self.client.connected and not await self.client.connect():
            logger.error(f"[Bus] connect failed (slave={self.slave_id})")
            return False

        try:
            resp = await self.client.write_coil(address=offset, value=value, slave=self.slave_id)

            if resp.isError():
                logger.warning(f"[Bus] Coil write error: {resp}")
                return False

            logger.debug(f"[Bus] Write coil success: address={offset}, value={value}")
            return True

        except Exception as e:
            logger.error(f"[Bus] Exception writing coil: {e}")
            return False

    async def write_coils(self, offset: int, values: list[bool]) -> bool:
        """
        Write multiple Coils (Function Code 15).

        Args:
            offset: Starting coil address (0-based)
            values: list of coil states

        Returns:
            bool: Write success (True=success, False=failed)
        """
        if not self.client.connected and not await self.client.connect():
            logger.error(f"[Bus] connect failed (slave={self.slave_id})")
            return False

        try:
            resp = await self.client.write_coils(address=offset, values=values, slave=self.slave_id)

            if resp.isError():
                logger.warning(f"[Bus] Coils write error: {resp}")
                return False

            logger.debug(f"[Bus] Write coils success: address={offset}, count={len(values)}")
            return True

        except Exception as e:
            logger.error(f"[Bus] Exception writing coils: {e}")
            return False

    # ==================== New Discrete Input methods ====================

    async def read_discrete_input(self, offset: int) -> int:
        """
        Read a single Discrete Input (Function Code 02).

        Args:
            offset: Discrete input address (0-based)

        Returns:
            int: Input state (1=ON, 0=OFF, -1=READ_FAILED)
        """
        inputs = await self.read_discrete_inputs(offset, 1)
        return inputs[0]

    async def read_discrete_inputs(self, offset: int, count: int) -> list[int]:
        """
        Read multiple Discrete Inputs (Function Code 02).

        Args:
            offset: Starting discrete input address (0-based)
            count: Number of inputs to read

        Returns:
            List[int]: Input states (1=ON, 0=OFF, -1=READ_FAILED)
        """
        if not self.client.connected and not await self.client.connect():
            logger.error(f"[Bus] connect failed (slave={self.slave_id}), return missing values")
            return [DEFAULT_MISSING_VALUE] * count

        try:
            resp = await self.client.read_discrete_inputs(address=offset, count=count, slave=self.slave_id)

            if resp.isError():
                logger.warning(f"[Bus] Discrete input read error: {resp}")
                return [DEFAULT_MISSING_VALUE] * count

            # Convert bool to int: True→1, False→0
            return [1 if bit else 0 for bit in resp.bits[:count]]

        except Exception as e:
            logger.error(f"[Bus] Exception reading discrete inputs: {e}")
            return [DEFAULT_MISSING_VALUE] * count

    # ==================== Helper methods ====================

    async def read_value_by_type(self, offset: int, count: int = 1):
        """
        Automatically select a read method based on register_type.

        Args:
            offset: Address
            count: Number of values to read

        Returns:
            Values read:
              - registers/coil/discrete_input -> list[int]
        """
        if self.register_type == RegisterType.HOLDING or self.register_type == RegisterType.INPUT:
            return await self.read_regs(offset, count)
        elif self.register_type == RegisterType.COIL:
            return await self.read_coils(offset, count)
        elif self.register_type == RegisterType.DISCRETE_INPUT:
            return await self.read_discrete_inputs(offset, count)
        else:
            logger.error(f"[Bus] Unknown register_type: {self.register_type}")
            return [DEFAULT_MISSING_VALUE] * count

    async def write_value_by_type(self, offset: int, value) -> bool:
        """
        Automatically select a write method based on register_type.

        Args:
            offset: Address
            value: Value to write (int for register, bool for coil)

        Returns:
            bool: Write success
        """
        if self.register_type == RegisterType.HOLDING:
            await self.write_u16(offset, int(value))
            return True
        elif self.register_type == RegisterType.COIL:
            return await self.write_coil(offset, bool(value))
        else:
            logger.error(f"[Bus] Cannot write to register_type: {self.register_type}")
            return False
