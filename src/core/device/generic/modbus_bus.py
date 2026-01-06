import asyncio
import logging
from typing import Any, Coroutine

from pymodbus.client import AsyncModbusSerialClient
from pymodbus.pdu.pdu import ModbusPDU

from core.model.device_constant import DEFAULT_MISSING_VALUE
from core.model.enum.register_type_enum import RegisterType

logger = logging.getLogger("ModbusBus")


class ModbusBus:
    """
    Cancel-safe ModbusBus for RS-485 with aggressive buffer management.

    Key strategy changes:
    - ALWAYS clear RX buffer BEFORE each request (prevents slave ID confusion)
    - Selective connection reset based on error severity
    - Reduced log verbosity for common errors

    Critical for preventing "expected id X but got Y" errors in multi-device RS-485 environments.
    """

    # Modbus exception codes (for error classification)
    ILLEGAL_FUNCTION = 1
    ILLEGAL_DATA_ADDRESS = 2
    ILLEGAL_DATA_VALUE = 3
    SLAVE_DEVICE_FAILURE = 4
    ACKNOWLEDGE = 5
    SLAVE_DEVICE_BUSY = 6
    MEMORY_PARITY_ERROR = 8
    GATEWAY_PATH_UNAVAILABLE = 10
    GATEWAY_TARGET_FAILED = 11

    def __init__(
        self,
        client: AsyncModbusSerialClient,
        slave_id: int,
        register_type: str,
        lock: asyncio.Lock | None = None,
    ):
        self.client = client
        self.slave_id = int(slave_id)
        self.register_type = register_type
        self.lock = lock

        # Track consecutive errors for adaptive behavior
        self._consecutive_errors = 0
        self._max_errors_before_reset = 3

    # ==================== Public API ====================

    async def read_u16(self, offset: int) -> int:
        regs = await self.read_regs(offset, 1)
        return int(regs[0]) if regs else DEFAULT_MISSING_VALUE

    async def read_regs(self, offset: int, count: int) -> list[int]:
        """
        Read multiple registers with PRE-REQUEST buffer clearing.

        Critical behavior:
        1. Clear RX buffer BEFORE sending request (not after errors)
        2. Small delay after clearing to let it propagate
        3. Selective connection reset based on error type
        """
        async with self._lock_context():
            if not await self._ensure_connected_locked():
                logger.error(f"[Bus] connect failed (slave={self.slave_id}), return missing values")
                return [DEFAULT_MISSING_VALUE] * count

            # CRITICAL: Clear buffer BEFORE request
            buffer_cleared = self._try_clear_receive_buffer()
            logger.debug(f"[DEBUG][Bus][Slave {self.slave_id}] Buffer clear result: {buffer_cleared}")

            # Small delay to let buffer clear propagate
            await asyncio.sleep(0.01)  # 10ms

            try:
                logger.debug(
                    f"[DEBUG][Bus][Slave {self.slave_id}] Sending request: "
                    f"type={self.register_type}, offset={offset}, count={count}"
                )

                if self.register_type in (RegisterType.HOLDING, "holding"):
                    resp: ModbusPDU = await self.client.read_holding_registers(
                        address=int(offset),
                        count=int(count),
                        slave=int(self.slave_id),
                    )
                elif self.register_type in (RegisterType.INPUT, "input"):
                    resp: ModbusPDU = await self.client.read_input_registers(
                        address=int(offset),
                        count=int(count),
                        slave=int(self.slave_id),
                    )
                elif self.register_type in (RegisterType.COIL, "coil"):
                    resp: ModbusPDU = await self.client.read_coils(
                        address=int(offset),
                        count=int(count),
                        slave=int(self.slave_id),
                    )
                elif self.register_type in (RegisterType.DISCRETE_INPUT, "discrete_input"):
                    resp: ModbusPDU = await self.client.read_discrete_inputs(
                        address=int(offset),
                        count=int(count),
                        slave=int(self.slave_id),
                    )
                else:
                    logger.error(f"[Bus] Unsupported register type for read_regs: {self.register_type}")
                    return [DEFAULT_MISSING_VALUE] * count

                logger.debug(
                    f"[DEBUG][Bus][Slave {self.slave_id}] <<< Received response: "
                    f"isError={resp.isError()}, type={type(resp).__name__}"
                )

                if resp.isError():
                    return await self._handle_modbus_error(resp, offset, count)

                # ---- decode payload by register_type ----
                if self.register_type in (RegisterType.COIL, "coil", RegisterType.DISCRETE_INPUT, "discrete_input"):
                    try:
                        bits = resp.bits
                    except AttributeError:
                        bits = None

                    if isinstance(bits, list) and len(bits) >= count:
                        self._consecutive_errors = 0
                        return [1 if b else 0 for b in bits[:count]]

                    logger.error(
                        f"[Bus][Slave {self.slave_id}] Invalid bit payload: "
                        f"bits_type={type(bits)}, bits_len={len(bits) if isinstance(bits, list) else 'N/A'}"
                    )
                    await self._reset_connection_locked(reason="invalid_bit_payload", force_close=True)
                    return [DEFAULT_MISSING_VALUE] * count

                # holding/input path
                try:
                    regs = resp.registers
                except AttributeError:
                    regs = None

                if isinstance(regs, list) and len(regs) >= count:
                    self._consecutive_errors = 0
                    return regs[:count]

                logger.error(
                    f"[Bus][Slave {self.slave_id}] Invalid payload: "
                    f"regs_type={type(regs)}, regs_len={len(regs) if isinstance(regs, list) else 'N/A'}"
                )
                await self._reset_connection_locked(reason="invalid_payload", force_close=True)
                return [DEFAULT_MISSING_VALUE] * count

            except asyncio.CancelledError:
                logger.warning(
                    f"[Bus] CancelledError during read_regs (slave={self.slave_id}, offset={offset}, count={count})"
                )
                # Cancellation → full reset to ensure clean state
                await self._reset_connection_locked(reason="cancelled", force_close=True)
                raise

            except Exception as exc:
                exc_str = str(exc).lower()
                is_transport_error = any(
                    keyword in exc_str for keyword in ["transport", "connection", "timeout", "serial", "i/o"]
                )

                if is_transport_error:
                    logger.warning(f"[Bus] Transport error during read_regs (slave={self.slave_id}): {exc}")
                    # Transport error → full reset
                    await self._reset_connection_locked(reason="transport_error", force_close=True)
                else:
                    logger.debug(f"[Bus] Exception during read_regs (slave={self.slave_id}): {exc}")
                    # Other exception → buffer clear only
                    await self._reset_connection_locked(reason="exception", force_close=False)

                return [DEFAULT_MISSING_VALUE] * count

    async def write_u16(self, offset: int, value: int) -> bool:
        """Write a single 16-bit register with PRE-REQUEST buffer clearing."""
        async with self._lock_context():
            if not await self._ensure_connected_locked():
                logger.error(f"[Bus] connect failed (slave={self.slave_id})")
                return False

            # Clear buffer before write
            self._try_clear_receive_buffer()
            await asyncio.sleep(0.01)

            try:
                resp: ModbusPDU = await self.client.write_register(
                    address=int(offset),
                    value=int(value),
                    slave=int(self.slave_id),
                )

                if resp.isError():
                    # Extract exception code without getattr
                    try:
                        exc_code = resp.exception_code
                    except AttributeError:
                        exc_code = 0

                    # Classify error severity
                    if exc_code in {self.ILLEGAL_DATA_ADDRESS, self.ILLEGAL_DATA_VALUE, self.ILLEGAL_FUNCTION}:
                        # Device configuration error → buffer clear only
                        logger.debug(f"[Bus] Write config error (slave={self.slave_id}, code={exc_code})")
                        await self._reset_connection_locked(reason=f"write_error_{exc_code}", force_close=False)
                    else:
                        # Severe error → full reset
                        logger.warning(f"[Bus] Write error (slave={self.slave_id}, code={exc_code})")
                        await self._reset_connection_locked(reason=f"write_error_{exc_code}", force_close=True)

                    return False

                # Success
                self._consecutive_errors = 0
                return True

            except asyncio.CancelledError:
                logger.warning(f"[Bus] CancelledError during write_u16 (slave={self.slave_id}, offset={offset})")
                await self._reset_connection_locked(reason="cancelled", force_close=True)
                raise

            except Exception as exc:
                logger.warning(f"[Bus] Exception during write_u16 (slave={self.slave_id}): {exc}")
                await self._reset_connection_locked(reason="write_exception", force_close=True)
                return False

    async def read_coil(self, offset: int) -> int:
        coils = await self.read_coils(offset, 1)
        return coils[0] if coils else DEFAULT_MISSING_VALUE

    async def read_coils(self, offset: int, count: int) -> list[int]:
        """Read coils with PRE-REQUEST buffer clearing."""
        async with self._lock_context():
            if not await self._ensure_connected_locked():
                logger.error(f"[Bus] connect failed (slave={self.slave_id}), return missing values")
                return [DEFAULT_MISSING_VALUE] * count

            # Clear buffer before request
            self._try_clear_receive_buffer()
            await asyncio.sleep(0.01)

            try:
                resp: ModbusPDU = await self.client.read_coils(
                    address=int(offset),
                    count=int(count),
                    slave=int(self.slave_id),
                )

                if resp.isError():
                    # Extract exception code without getattr
                    try:
                        exc_code = resp.exception_code
                    except AttributeError:
                        exc_code = 0

                    # Same classification logic as read_regs
                    if exc_code in {self.ILLEGAL_DATA_ADDRESS, self.ILLEGAL_FUNCTION}:
                        logger.debug(f"[Bus] Coil config error (slave={self.slave_id}, code={exc_code})")
                        await self._reset_connection_locked(reason=f"coil_error_{exc_code}", force_close=False)
                    else:
                        logger.warning(f"[Bus] Coil read error (slave={self.slave_id}, code={exc_code})")
                        await self._reset_connection_locked(reason=f"coil_error_{exc_code}", force_close=True)

                    return [DEFAULT_MISSING_VALUE] * count

                # Extract bits without getattr
                try:
                    bits = resp.bits
                except AttributeError:
                    bits = None

                if not isinstance(bits, list):
                    logger.warning(f"[Bus] Invalid coil payload (slave={self.slave_id})")
                    await self._reset_connection_locked(reason="invalid_coil_payload", force_close=True)
                    return [DEFAULT_MISSING_VALUE] * count

                out = [1 if bit else 0 for bit in bits[:count]]
                if len(out) < count:
                    out.extend([DEFAULT_MISSING_VALUE] * (count - len(out)))

                self._consecutive_errors = 0
                return out

            except asyncio.CancelledError:
                await self._reset_connection_locked(reason="cancelled", force_close=True)
                raise
            except Exception as exc:
                logger.debug(f"[Bus] Exception during read_coils (slave={self.slave_id}): {exc}")
                await self._reset_connection_locked(reason="coil_exception", force_close=False)
                return [DEFAULT_MISSING_VALUE] * count

    async def write_coil(self, offset: int, value: bool) -> bool:
        """Write single coil with PRE-REQUEST buffer clearing."""
        async with self._lock_context():
            if not await self._ensure_connected_locked():
                logger.error(f"[Bus] connect failed (slave={self.slave_id})")
                return False

            # Clear buffer before write
            self._try_clear_receive_buffer()
            await asyncio.sleep(0.01)

            try:
                resp: ModbusPDU = await self.client.write_coil(
                    address=int(offset),
                    value=bool(value),
                    slave=int(self.slave_id),
                )

                if resp.isError():
                    try:
                        exc_code = resp.exception_code
                    except AttributeError:
                        exc_code = 0

                    logger.debug(f"[Bus] Coil write error (slave={self.slave_id}, code={exc_code})")
                    await self._reset_connection_locked(reason=f"write_coil_error_{exc_code}", force_close=False)
                    return False

                self._consecutive_errors = 0
                return True

            except asyncio.CancelledError:
                await self._reset_connection_locked(reason="cancelled", force_close=True)
                raise
            except Exception as exc:
                logger.warning(f"[Bus] Exception during write_coil (slave={self.slave_id}): {exc}")
                await self._reset_connection_locked(reason="write_coil_exception", force_close=True)
                return False

    async def write_coils(self, offset: int, values: list[bool]) -> bool:
        """Write multiple coils with PRE-REQUEST buffer clearing."""
        async with self._lock_context():
            if not await self._ensure_connected_locked():
                logger.error(f"[Bus] connect failed (slave={self.slave_id})")
                return False

            # Clear buffer before write
            self._try_clear_receive_buffer()
            await asyncio.sleep(0.01)

            try:
                resp: ModbusPDU = await self.client.write_coils(
                    address=int(offset),
                    values=list(values),
                    slave=int(self.slave_id),
                )

                if resp.isError():
                    try:
                        exc_code = resp.exception_code
                    except AttributeError:
                        exc_code = 0

                    logger.debug(f"[Bus] Coils write error (slave={self.slave_id}, code={exc_code})")
                    await self._reset_connection_locked(reason=f"write_coils_error_{exc_code}", force_close=False)
                    return False

                self._consecutive_errors = 0
                return True

            except asyncio.CancelledError:
                await self._reset_connection_locked(reason="cancelled", force_close=True)
                raise
            except Exception as exc:
                logger.warning(f"[Bus] Exception during write_coils (slave={self.slave_id}): {exc}")
                await self._reset_connection_locked(reason="write_coils_exception", force_close=True)
                return False

    async def read_discrete_input(self, offset: int) -> int:
        inputs = await self.read_discrete_inputs(offset, 1)
        return inputs[0] if inputs else DEFAULT_MISSING_VALUE

    async def read_discrete_inputs(self, offset: int, count: int) -> list[int]:
        """Read discrete inputs with PRE-REQUEST buffer clearing."""
        async with self._lock_context():
            if not await self._ensure_connected_locked():
                logger.error(f"[Bus] connect failed (slave={self.slave_id}), return missing values")
                return [DEFAULT_MISSING_VALUE] * count

            # Clear buffer before request
            self._try_clear_receive_buffer()
            await asyncio.sleep(0.01)

            try:
                resp: ModbusPDU = await self.client.read_discrete_inputs(
                    address=int(offset),
                    count=int(count),
                    slave=int(self.slave_id),
                )

                if resp.isError():
                    try:
                        exc_code = resp.exception_code
                    except AttributeError:
                        exc_code = 0

                    if exc_code in {self.ILLEGAL_DATA_ADDRESS, self.ILLEGAL_FUNCTION}:
                        logger.debug(f"[Bus] Discrete input config error (slave={self.slave_id}, code={exc_code})")
                        await self._reset_connection_locked(reason=f"discrete_error_{exc_code}", force_close=False)
                    else:
                        logger.warning(f"[Bus] Discrete input read error (slave={self.slave_id}, code={exc_code})")
                        await self._reset_connection_locked(reason=f"discrete_error_{exc_code}", force_close=True)

                    return [DEFAULT_MISSING_VALUE] * count

                # Extract bits without getattr
                try:
                    bits = resp.bits
                except AttributeError:
                    bits = None

                if not isinstance(bits, list):
                    logger.warning(f"[Bus] Invalid discrete payload (slave={self.slave_id})")
                    await self._reset_connection_locked(reason="invalid_discrete_payload", force_close=True)
                    return [DEFAULT_MISSING_VALUE] * count

                out = [1 if bit else 0 for bit in bits[:count]]
                if len(out) < count:
                    out.extend([DEFAULT_MISSING_VALUE] * (count - len(out)))

                self._consecutive_errors = 0
                return out

            except asyncio.CancelledError:
                await self._reset_connection_locked(reason="cancelled", force_close=True)
                raise
            except Exception as exc:
                logger.debug(f"[Bus] Exception during read_discrete_inputs (slave={self.slave_id}): {exc}")
                await self._reset_connection_locked(reason="discrete_exception", force_close=False)
                return [DEFAULT_MISSING_VALUE] * count

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
        """Public connectivity check (acquires lock before connect)."""
        if self.client.connected:
            return True

        async with self._lock_context():
            return await self._ensure_connected_locked()

    # ==================== Internal helpers ====================

    async def _handle_modbus_error(self, resp: ModbusPDU, offset: int, count: int) -> list[int]:
        """
        Classify Modbus error response and apply appropriate reset strategy.

        Device configuration errors (2, 3, 4):
        - Don't close connection (waste of time, error will persist)
        - Clear buffer only (prevents slave ID confusion)

        Other errors (timeout, bus busy, unknown):
        - Close connection if errors accumulate
        - Always clear buffer
        """
        # Extract exception code without getattr
        try:
            exc_code = resp.exception_code
        except AttributeError:
            exc_code = 0

        self._consecutive_errors += 1

        # Device configuration errors → buffer clear only
        if exc_code in {self.ILLEGAL_DATA_ADDRESS, self.ILLEGAL_DATA_VALUE, self.ILLEGAL_FUNCTION}:
            logger.debug(
                f"[Bus] Device config error (slave={self.slave_id}, code={exc_code}, "
                f"offset={offset}, count={count})"
            )
            await self._reset_connection_locked(reason=f"modbus_error_{exc_code}", force_close=False)
            return [DEFAULT_MISSING_VALUE] * count

        # Device busy → buffer clear, close if too many consecutive errors
        if exc_code == self.SLAVE_DEVICE_BUSY:
            logger.debug(f"[Bus] Device busy (slave={self.slave_id})")
            force_close = self._consecutive_errors >= self._max_errors_before_reset
            await self._reset_connection_locked(reason="device_busy", force_close=force_close)
            return [DEFAULT_MISSING_VALUE] * count

        # Severe/unknown errors → full reset
        logger.warning(
            f"[Bus] Modbus error (slave={self.slave_id}, code={exc_code}, " f"offset={offset}, count={count})"
        )
        await self._reset_connection_locked(reason=f"modbus_error_{exc_code}", force_close=True)
        return [DEFAULT_MISSING_VALUE] * count

    async def _ensure_connected_locked(self) -> bool:
        """Must be called under port lock."""
        if self.client.connected:
            return True

        await self._safe_close_client(reason="pre_reconnect_cleanup")

        try:
            ok = await self.client.connect()
            if not ok:
                logger.error(f"[Bus] connect failed (slave={self.slave_id})")
            return bool(ok)
        except Exception as exc:
            logger.warning(f"[Bus] connect exception (slave={self.slave_id}): {exc}")
            await self._reset_connection_locked(reason="connect_exception", force_close=True)
            return False

    async def _reset_connection_locked(self, reason: str, force_close: bool = False) -> None:
        """
        Selective reset strategy (must be called under port lock).

        Always:
        - Clear RX buffer (prevents slave ID confusion from stale frames)

        Conditionally (force_close=True):
        - Close client connection (forces reconnect on next request)

        When to force_close:
        - Transport errors (serial/connection issues)
        - Cancellation (ensure clean state)
        - Payload corruption (invalid/short data)
        - Too many consecutive errors
        - Unknown/severe Modbus errors

        When NOT to force_close:
        - Device configuration errors (ILLEGAL_ADDRESS, VALUE, FUNCTION)
        - Device busy (temporary state)
        - Normal exceptions (let Health Manager handle)
        """
        # Always clear buffer to prevent slave ID confusion
        self._try_clear_receive_buffer()

        # Optionally close connection
        if force_close:
            await self._safe_close_client(reason=reason)
        else:
            logger.debug(f"[Bus] Buffer cleared (slave={self.slave_id}, reason={reason})")

    def _try_clear_receive_buffer(self) -> bool:
        """
        Clear serial RX buffer via ctx.transport.sync_serial.

        Critical for RS-485: Prevents stale frames from causing slave ID confusion.
        """
        # Direct path for pymodbus 3.x: ctx.transport.sync_serial
        try:
            ctx = self.client.ctx
            if ctx is not None:
                transport = ctx.transport
                if transport is not None:
                    # Primary path: sync_serial (confirmed working)
                    try:
                        serial = transport.sync_serial
                        if serial is not None:
                            # Try to call reset_input_buffer
                            try:
                                serial.reset_input_buffer()
                                logger.debug(f"[Bus][Slave {self.slave_id}] Buffer cleared")
                                return True
                            except AttributeError:
                                # Method doesn't exist on this serial object
                                pass
                    except AttributeError:
                        # sync_serial attribute doesn't exist
                        pass
        except AttributeError:
            # ctx or transport doesn't exist
            pass
        except Exception as e:
            logger.debug(f"[Bus][Slave {self.slave_id}] Buffer clear failed: {e}")

        # Show warning only once per slave instance
        try:
            # Check if warning already shown (will raise AttributeError if not)
            _ = self._buffer_clear_warning_shown
        except AttributeError:
            # First time - show warning and mark as shown
            self._buffer_clear_warning_shown = True
            logger.warning(f"[Bus][Slave {self.slave_id}] Could not access serial buffer")

        return False

    async def _safe_close_client(self, reason: str) -> None:
        """
        Best-effort close supporting both sync and async implementations.
        """
        try:
            close_ret = self.client.close()
            if asyncio.iscoroutine(close_ret) or isinstance(close_ret, Coroutine):
                await close_ret
            logger.debug(f"[Bus] Connection closed (slave={self.slave_id}, reason={reason})")
        except Exception as exc:
            logger.debug(f"[Bus] Close failed (slave={self.slave_id}, reason={reason}): {exc}")

    def _lock_context(self):
        return self.lock if self.lock else _NullAsyncLock()


class _NullAsyncLock:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False
