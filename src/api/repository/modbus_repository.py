"""
Modbus Data Access Layer

Encapsulates all Modbus communication logic.
Provides low-level interfaces for device read/write operations.
"""

import asyncio
import logging
import time
from typing import Any

from pymodbus.client import AsyncModbusSerialClient
from pymodbus.exceptions import ModbusException

from api.repository.config_repository import ConfigRepository

logger = logging.getLogger(__name__)


class ModbusRepository:
    """Modbus communication data access layer"""

    _instance = None
    _initialized = False

    def __new__(cls):
        """Implement singleton pattern"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize the Modbus Repository"""
        if not self._initialized:
            self._client: AsyncModbusSerialClient | None = None
            self._device_configs: dict[str, dict[str, Any]] = {}
            self._lock = asyncio.Lock()

            #  New: device status cache
            self._device_status: dict[str, dict[str, Any]] = {}
            # Format: {device_id: {"is_online": bool, "last_check": timestamp, "failure_count": int}}
            self._register_locks: dict[tuple, asyncio.Lock] = {}
            self.__class__._initialized = True

    async def initialize(self):
        """Initialize Modbus serial connection"""
        list

        config_repo = ConfigRepository()
        self._device_configs = config_repo.get_all_device_configs()

        if self._device_configs:
            first_device = next(iter(self._device_configs.values()))
            port = first_device.get("port", "/dev/ttyUSB0")

            # Establish serial connection
            timeout = 1
            retries = 0
            self._client = AsyncModbusSerialClient(
                port=port,
                baudrate=9600,
                bytesize=8,
                parity="N",
                stopbits=1,
                timeout=timeout,
                retries=retries,
            )

            await self._client.connect()
            logger.info(f"Initialized Modbus serial connection on {port} (timeout={timeout}s, retries={retries})")

        logger.info(f"Loaded configuration for {len(self._device_configs)} devices")

    async def cleanup(self):
        """Clean up Modbus connection"""
        if self._client:
            self._client.close()
            logger.info("Closed Modbus serial connection")

    def get_device_status(self, device_id: str) -> dict[str, Any]:
        """
        Get cached device status.

        Returns:
            Dict: {"is_online": bool, "last_check": float, "failure_count": int}
        """
        return self._device_status.get(device_id, {"is_online": None, "last_check": 0, "failure_count": 0})  # Unknown

    def clear_device_status(self, device_id: str):
        """Clear cached device status"""
        if device_id in self._device_status:
            del self._device_status[device_id]
            logger.info(f"[STATUS] Cleared status cache for {device_id}")

    async def test_connection(self, device_id: str, use_cache: bool = True) -> bool:
        """
        Test device connectivity.

        Args:
            device_id: Device identifier.
            use_cache: Whether to use cache (default True).

        Returns:
            bool: Whether the connection is healthy.
        """
        try:
            current_time = time.time()
            status = self._device_status.get(device_id, {})
            last_check = status.get("last_check", 0)

            #  Use cache: if checked within the last 5 seconds, return cached result
            if use_cache and (current_time - last_check < 5):
                cached_status = status.get("is_online", False)
                logger.debug(f"[CONNECTION] Using cached status for {device_id}: {cached_status}")
                return cached_status

            # Perform actual connectivity test
            if not self._client or not self._client.connected:
                self._device_status[device_id] = {
                    "is_online": False,
                    "last_check": current_time,
                    "failure_count": status.get("failure_count", 0) + 1,
                }
                return False

            device_config = self._device_configs.get(device_id)
            if not device_config:
                logger.error(f"[CONNECTION] Device {device_id} not found in configuration")
                return False

            slave_id = int(device_config["slave_id"])

            logger.debug(f"[CONNECTION] Testing connection to {device_id} (slave {slave_id})...")

            # Quick test: try reading register 0
            response = await self._client.read_holding_registers(address=0, count=1, slave=slave_id)

            is_online = not response.isError()

            #  Update cache
            self._device_status[device_id] = {
                "is_online": is_online,
                "last_check": current_time,
                "failure_count": 0 if is_online else status.get("failure_count", 0) + 1,
            }

            logger.info(f"[CONNECTION] {device_id} is {'online' if is_online else 'offline'}")

            return is_online

        except Exception as e:
            logger.error(f"[CONNECTION] Test failed for {device_id}: {e}")

            # Update cache as offline
            self._device_status[device_id] = {
                "is_online": False,
                "last_check": time.time(),
                "failure_count": status.get("failure_count", 0) + 1,
            }

            return False

    async def read_register(
        self,
        device_id: str,
        register_offset: int,
        register_type: str = "holding",
        combine_high_offset: int | None = None,
    ) -> int | None:
        """
        Read a Modbus register.

        Returns:
            Optional[int]: Register value, or None on failure.
        """
        try:
            if not self._client:
                logger.error("[MODBUS] Client not initialized")
                return None

            if not self._client.connected:
                logger.error("[MODBUS] Client not connected")
                return None

            device_config = self._device_configs.get(device_id)
            if not device_config:
                logger.error(f"[MODBUS] Device {device_id} not found in configuration")
                return None

            slave_id = int(device_config["slave_id"])

            # Normalize register_type
            if register_type not in ["holding", "input"]:
                logger.warning(f"[MODBUS] Invalid register type '{register_type}', defaulting to 'holding'")
                register_type = "holding"

            logger.info(
                f"[MODBUS READ] Device: {device_id}, Slave: {slave_id}, Offset: {register_offset}, Type: {register_type}"
            )

            # Handle 32-bit combined registers
            if combine_high_offset is not None:
                logger.debug(f"[MODBUS] Reading combined registers {register_offset} + {combine_high_offset}")

                response_low = await self._client.read_holding_registers(
                    address=register_offset, count=1, slave=slave_id
                )

                if response_low.isError():
                    logger.error(f"[MODBUS] Failed to read low register: {response_low}")
                    #  Mark device as possibly offline
                    self._mark_device_failure(device_id)
                    return None

                response_high = await self._client.read_holding_registers(
                    address=combine_high_offset, count=1, slave=slave_id
                )

                if response_high.isError():
                    logger.error(f"[MODBUS] Failed to read high register: {response_high}")
                    self._mark_device_failure(device_id)
                    return None

                low_word = response_low.registers[0]
                high_word = response_high.registers[0]
                combined_value = low_word + (high_word * 65536)

                logger.debug(f"[MODBUS] Combined: low={low_word}, high={high_word}, result={combined_value}")

                #  Read succeeded; mark device online
                self._mark_device_success(device_id)

                return combined_value

            # Normal 16-bit read
            if register_type == "holding":
                response = await self._client.read_holding_registers(address=register_offset, count=1, slave=slave_id)
            elif register_type == "input":
                response = await self._client.read_input_registers(address=register_offset, count=1, slave=slave_id)
            else:
                logger.error(f"[MODBUS] Unknown register type: {register_type}")
                return None

            if response.isError():
                logger.error(f"[MODBUS] Read error: {response}")
                #  Mark device as possibly offline
                self._mark_device_failure(device_id)
                return None

            raw_value = response.registers[0]
            logger.info(f"[MODBUS] Read success: offset={register_offset} -> raw_value={raw_value}")

            #  Read succeeded; mark device online
            self._mark_device_success(device_id)

            return raw_value

        except ModbusException as e:
            logger.error(f"[MODBUS] Modbus exception reading {device_id}: {e}")
            self._mark_device_failure(device_id)
            return None
        except Exception as e:
            logger.error(f"[MODBUS] Unexpected error reading {device_id}: {e}", exc_info=True)
            self._mark_device_failure(device_id)
            return None

    def _mark_device_success(self, device_id: str):
        """Mark device read success (online)"""
        self._device_status[device_id] = {"is_online": True, "last_check": time.time(), "failure_count": 0}

    def _mark_device_failure(self, device_id: str):
        """Mark device read failure (possibly offline)"""
        status = self._device_status.get(device_id, {})
        failure_count = status.get("failure_count", 0) + 1

        self._device_status[device_id] = {
            "is_online": False if failure_count >= 2 else status.get("is_online"),
            "last_check": time.time(),
            "failure_count": failure_count,
        }

    async def write_register(
        self, device_id: str, register_offset: int, value: int, register_type: str = "holding"
    ) -> bool:
        """
        Write a Modbus register.

        Uses a per-register lock to prevent concurrent write conflicts.
        """
        #  Acquire a dedicated lock for this register
        register_lock = self._get_register_lock(device_id, register_offset)

        async with register_lock:
            try:
                if not self._client:
                    logger.error("[MODBUS WRITE] Client not initialized")
                    return False

                if not self._client.connected:
                    logger.error("[MODBUS WRITE] Client not connected")
                    return False

                device_config = self._device_configs.get(device_id)
                if not device_config:
                    logger.error(f"[MODBUS WRITE] Device {device_id} not found")
                    return False

                slave_id = int(device_config["slave_id"])

                if register_type not in ["holding", "input"]:
                    logger.warning(f"[MODBUS WRITE] Invalid register type '{register_type}', defaulting to 'holding'")
                    register_type = "holding"

                logger.info(
                    f"[MODBUS WRITE] Device: {device_id}, Slave: {slave_id}, Offset: {register_offset}, Value: {value} (0b{bin(value)[2:].zfill(16)}), Type: {register_type}"
                )

                if register_type == "holding":
                    response = await self._client.write_register(address=register_offset, value=value, slave=slave_id)
                else:
                    logger.error(f"[MODBUS WRITE] Cannot write to register type: {register_type}")
                    raise ValueError(f"Cannot write to register type: {register_type}")

                if response.isError():
                    logger.error(f"[MODBUS WRITE] Write error: {response}")
                    self._mark_device_failure(device_id)
                    return False

                logger.info(f"[MODBUS WRITE]  Successfully wrote {value} to offset {register_offset}")
                self._mark_device_success(device_id)
                return True

            except Exception as e:
                logger.error(f"[MODBUS WRITE] Error writing to {device_id}: {e}", exc_info=True)
                self._mark_device_failure(device_id)
                return False

    def _get_register_lock(self, device_id: str, register_offset: int) -> asyncio.Lock:
        """
        Get the lock for a specific register.

        Prevents race conditions for concurrent read-modify-write operations on the same register.
        """
        key = (device_id, register_offset)
        if key not in self._register_locks:
            self._register_locks[key] = asyncio.Lock()
        return self._register_locks[key]

    async def read_modify_write_bit(
        self, device_id: str, register_offset: int, bit_position: int, bit_value: int, register_type: str = "holding"
    ) -> bool:
        """
        Atomic bit read-modify-write operation.

        Prevents bit overwrite issues caused by concurrent operations.

        Args:
            device_id: Device identifier.
            register_offset: Register offset address.
            bit_position: Bit position (0-15).
            bit_value: Bit value (0 or 1).
            register_type: Register type.

        Returns:
            bool: Whether the operation succeeded.
        """
        #  Acquire the dedicated lock for this register to protect the whole read-modify-write flow
        register_lock = self._get_register_lock(device_id, register_offset)

        async with register_lock:
            try:
                logger.info(
                    f"[BIT WRITE] Atomic operation: {device_id} offset={register_offset} bit={bit_position} value={bit_value}"
                )

                # Step 1: Read current register value
                current_value = await self._read_register_unlocked(
                    device_id=device_id, register_offset=register_offset, register_type=register_type
                )

                if current_value is None:
                    logger.error(f"[BIT WRITE] Failed to read current register value")
                    return False

                logger.info(f"[BIT WRITE] Current register: {current_value} (0b{bin(current_value)[2:].zfill(16)})")

                # Step 2: Modify the specified bit
                if bit_value == 1:
                    new_value = current_value | (1 << bit_position)
                else:
                    new_value = current_value & ~(1 << bit_position)

                logger.info(f"[BIT WRITE] New register: {new_value} (0b{bin(new_value)[2:].zfill(16)})")

                # Step 3: Write back to the register
                success = await self._write_register_unlocked(
                    device_id=device_id, register_offset=register_offset, value=new_value, register_type=register_type
                )

                if success:
                    logger.info(f"[BIT WRITE]  Atomic bit operation completed successfully")
                else:
                    logger.error(f"[BIT WRITE]  Atomic bit operation failed")

                return success

            except Exception as e:
                logger.error(f"[BIT WRITE] Exception during atomic operation: {e}", exc_info=True)
                return False

    async def _read_register_unlocked(
        self, device_id: str, register_offset: int, register_type: str = "holding"
    ) -> int | None:
        """
        Read a register (unlocked version).

        For internal use only; external callers should use `read_register`.
        """
        try:
            if not self._client or not self._client.connected:
                return None

            device_config = self._device_configs.get(device_id)
            if not device_config:
                return None

            slave_id = int(device_config["slave_id"])

            if register_type == "holding":
                response = await self._client.read_holding_registers(address=register_offset, count=1, slave=slave_id)
            elif register_type == "input":
                response = await self._client.read_input_registers(address=register_offset, count=1, slave=slave_id)
            else:
                return None

            if response.isError():
                return None

            return response.registers[0]

        except Exception as e:
            logger.error(f"[MODBUS] Read error: {e}")
            return None

    async def _write_register_unlocked(
        self, device_id: str, register_offset: int, value: int, register_type: str = "holding"
    ) -> bool:
        """
        Write a register (unlocked version).

        For internal use only; external callers should use `write_register`.
        """
        try:
            if not self._client or not self._client.connected:
                return False

            device_config = self._device_configs.get(device_id)
            if not device_config:
                return False

            slave_id = int(device_config["slave_id"])

            if register_type == "holding":
                response = await self._client.write_register(address=register_offset, value=value, slave=slave_id)
            else:
                return False

            if response.isError():
                return False

            self._mark_device_success(device_id)
            return True

        except Exception as e:
            logger.error(f"[MODBUS] Write error: {e}")
            self._mark_device_failure(device_id)
            return False
