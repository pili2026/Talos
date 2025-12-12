import asyncio
import logging
from typing import Any

from pymodbus.client import AsyncModbusSerialClient
from pymodbus.pdu.pdu import ModbusPDU

from core.model.device_constant import DEFAULT_MISSING_VALUE
from core.model.enum.register_type_enum import RegisterType

logger = logging.getLogger("ModbusBus")


class ModbusBus:
    def __init__(
        self,
        client: AsyncModbusSerialClient,
        slave_id: int,
        register_type: str,
        lock: asyncio.Lock | None = None,
    ):
        """
        Initialize ModbusBus.

        Args:
            client: pymodbus AsyncModbusSerialClient
            slave_id: Modbus slave address
            register_type: "holding", "input", "coil", or "discrete_input"
            lock: per-port asyncio.Lock, to serialize all Modbus I/O on the same serial port
        """
        self.client = client
        self.slave_id = int(slave_id)
        self.register_type = register_type
        self.lock = lock

    # ==================== Original register methods ====================

    async def read_u16(self, offset: int) -> int:
        """Read a single 16-bit register."""
        regs = await self.read_regs(offset, 1)
        return int(regs[0]) if regs else DEFAULT_MISSING_VALUE

    async def read_regs(self, offset: int, count: int) -> list[int]:
        """Read multiple registers (holding/input)."""
        async with await self._lock_context():
            if not self.client.connected and not await self.client.connect():
                logger.error(f"[Bus] connect failed (slave={self.slave_id}), return missing values")
                return [DEFAULT_MISSING_VALUE] * count

            if self.register_type in (RegisterType.HOLDING, "holding"):
                resp: ModbusPDU = await self.client.read_holding_registers(
                    address=offset, count=count, slave=self.slave_id
                )
            elif self.register_type in (RegisterType.INPUT, "input"):
                resp: ModbusPDU = await self.client.read_input_registers(
                    address=offset, count=count, slave=self.slave_id
                )
            else:
                logger.error(f"[Bus] Unsupported register type for read_regs: {self.register_type}")
                return [DEFAULT_MISSING_VALUE] * count

            if resp.isError():
                logger.warning(f"[Bus] Modbus error response: {resp}")
                return [DEFAULT_MISSING_VALUE] * count

            regs = getattr(resp, "registers", None)
            if not isinstance(regs, list):
                return [DEFAULT_MISSING_VALUE] * count
            return regs

    async def write_u16(self, offset: int, value: int) -> bool:
        """Write a single 16-bit register (holding)."""
        async with await self._lock_context():
            if not self.client.connected and not await self.client.connect():
                logger.error(f"[Bus] connect failed (slave={self.slave_id})")
                return False

            try:
                resp: ModbusPDU = await self.client.write_register(
                    address=offset, value=int(value), slave=self.slave_id
                )
                if resp.isError():
                    logger.warning(f"[Bus] Register write error: {resp}")
                    return False
                return True
            except Exception as e:
                logger.error(f"[Bus] Exception writing register: {e}")
                return False

    # ==================== Coil methods ====================

    async def read_coil(self, offset: int) -> int:
        coils = await self.read_coils(offset, 1)
        return coils[0]

    async def read_coils(self, offset: int, count: int) -> list[int]:
        async with await self._lock_context():
            if not self.client.connected and not await self.client.connect():
                logger.error(f"[Bus] connect failed (slave={self.slave_id}), return missing values")
                return [DEFAULT_MISSING_VALUE] * count

            try:
                resp: ModbusPDU = await self.client.read_coils(address=offset, count=count, slave=self.slave_id)
                if resp.isError():
                    logger.warning(f"[Bus] Coil read error: {resp}")
                    return [DEFAULT_MISSING_VALUE] * count

                bits = getattr(resp, "bits", None)
                if not isinstance(bits, list):
                    return [DEFAULT_MISSING_VALUE] * count

                return [1 if bit else 0 for bit in bits[:count]]

            except Exception as e:
                logger.error(f"[Bus] Exception reading coils: {e}")
                return [DEFAULT_MISSING_VALUE] * count

    async def write_coil(self, offset: int, value: bool) -> bool:
        async with await self._lock_context():
            if not self.client.connected and not await self.client.connect():
                logger.error(f"[Bus] connect failed (slave={self.slave_id})")
                return False

            try:
                resp: ModbusPDU = await self.client.write_coil(address=offset, value=bool(value), slave=self.slave_id)
                if resp.isError():
                    logger.warning(f"[Bus] Coil write error: {resp}")
                    return False
                logger.debug(f"[Bus] Write coil success: address={offset}, value={value}")
                return True
            except Exception as e:
                logger.error(f"[Bus] Exception writing coil: {e}")
                return False

    async def write_coils(self, offset: int, values: list[bool]) -> bool:
        async with await self._lock_context():
            if not self.client.connected and not await self.client.connect():
                logger.error(f"[Bus] connect failed (slave={self.slave_id})")
                return False

            try:
                resp: ModbusPDU = await self.client.write_coils(address=offset, values=values, slave=self.slave_id)
                if resp.isError():
                    logger.warning(f"[Bus] Coils write error: {resp}")
                    return False
                logger.debug(f"[Bus] Write coils success: address={offset}, count={len(values)}")
                return True
            except Exception as e:
                logger.error(f"[Bus] Exception writing coils: {e}")
                return False

    # ==================== Discrete Input methods ====================

    async def read_discrete_input(self, offset: int) -> int:
        inputs: list[int] = await self.read_discrete_inputs(offset, 1)
        return inputs[0]

    async def read_discrete_inputs(self, offset: int, count: int) -> list[int]:
        async with await self._lock_context():
            if not self.client.connected and not await self.client.connect():
                logger.error(f"[Bus] connect failed (slave={self.slave_id}), return missing values")
                return [DEFAULT_MISSING_VALUE] * count

            try:
                resp: ModbusPDU = await self.client.read_discrete_inputs(
                    address=offset, count=count, slave=self.slave_id
                )
                if resp.isError():
                    logger.warning(f"[Bus] Discrete input read error: {resp}")
                    return [DEFAULT_MISSING_VALUE] * count

                bits = getattr(resp, "bits", None)
                if not isinstance(bits, list):
                    return [DEFAULT_MISSING_VALUE] * count

                return [1 if bit else 0 for bit in bits[:count]]

            except Exception as e:
                logger.error(f"[Bus] Exception reading discrete inputs: {e}")
                return [DEFAULT_MISSING_VALUE] * count

    # ==================== Helper methods ====================

    async def read_value_by_type(self, offset: int, count: int = 1) -> list[int]:
        if self.register_type in (RegisterType.HOLDING, "holding"):
            return await self.read_regs(offset, count)
        if self.register_type in (RegisterType.INPUT, "input"):
            return await self.read_regs(offset, count)
        if self.register_type in (RegisterType.COIL, "coil"):
            return await self.read_coils(offset, count)
        if self.register_type in (RegisterType.DISCRETE_INPUT, "discrete_input"):
            return await self.read_discrete_inputs(offset, count)

        logger.error(f"[Bus] Unknown register_type: {self.register_type}")
        return [DEFAULT_MISSING_VALUE] * count

    async def write_value_by_type(self, offset: int, value: Any) -> bool:
        if self.register_type in (RegisterType.HOLDING, "holding"):
            return await self.write_u16(offset, int(value))
        if self.register_type in (RegisterType.COIL, "coil"):
            return await self.write_coil(offset, bool(value))

        logger.error(f"[Bus] Cannot write to register_type: {self.register_type}")
        return False

    async def ensure_connected(self) -> bool:
        """
        Ensure the Modbus connection is established.

        IMPORTANT:
        - Acquire port lock before calling connect() to avoid concurrent open/connect.
        - Double-check inside lock to prevent duplicate connects.
        """
        if self.client.connected:
            return True

        async with await self._lock_context():
            if self.client.connected:
                return True

            is_ok: bool = await self.client.connect()
            if not is_ok:
                logger.error(f"[Bus] connect failed (slave={self.slave_id})")
            return is_ok

    async def _lock_context(self):
        """
        Internal helper: use lock if provided, else a no-op context.
        """
        if self.lock:
            return self.lock
        return _NullAsyncLock()


class _NullAsyncLock:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False
