import asyncio
import inspect
import logging
import os

from pymodbus.client import AsyncModbusSerialClient

from core.device.generic.constraints_policy import ConstraintPolicy
from core.device.generic.generic_device import AsyncGenericModbusDevice
from core.model.device_constant import DEFAULT_MISSING_VALUE
from core.schema.constraint_schema import ConstraintConfig, ConstraintConfigSchema
from core.util.config_manager import ConfigManager

logger = logging.getLogger("DeviceManager")


def _deep_merge_dicts(base: dict, override: dict) -> dict:
    """Shallow-safe deep merge for 2-level dicts (enough for modes tables)."""
    if not isinstance(base, dict):
        base = {}
    if not isinstance(override, dict):
        return dict(base)
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            nested = dict(out[k])
            nested.update(v)
            out[k] = nested
        else:
            out[k] = v
    return out


class AsyncDeviceManager:
    def __init__(
        self, config_path: str, constraint_config_schema: ConstraintConfigSchema, model_base_path: str = "./res"
    ):
        self.device_list: list[AsyncGenericModbusDevice] = []
        self.client_dict: dict[str, AsyncModbusSerialClient] = {}
        self.config_path = config_path
        self.constraint_config_schema = constraint_config_schema
        self.model_base_path = model_base_path

        self.driver_config_by_model: dict[str, dict] = {}

        self._port_locks: dict[str, asyncio.Lock] = {}

    async def init(self):
        config: dict = ConfigManager().load_yaml_file(self.config_path)

        for device_config in config.get("devices", []):
            model_path: str = os.path.join(self.model_base_path, device_config["model_file"])
            model_config: dict = ConfigManager().load_yaml_file(model_path)

            model: str = model_config["model"]
            if model not in self.driver_config_by_model:
                # NOTE: Check model_config reference to avoid re-loading same model file
                self.driver_config_by_model[model] = model_config

            # cast slave_id to int to be safe for pymodbus
            slave_id: int = int(device_config["slave_id"])
            port: str = device_config["port"]

            if port not in self._port_locks:
                self._port_locks[port] = asyncio.Lock()

            if port not in self.client_dict:
                client = AsyncModbusSerialClient(port=port, baudrate=9600, timeout=1)
                connected: bool = await client.connect()
                if not connected:
                    logger.warning(f"Failed to connect to port {port}")
                self.client_dict[port] = client

            # Use schema to get instance-level constraints
            instance_constraints: dict[str, ConstraintConfig] = ConfigManager.get_instance_constraints_from_schema(
                self.constraint_config_schema, model, slave_id
            )

            constraint_policy = ConstraintPolicy(instance_constraints, logger)

            # pass tables/modes into device; allow per-device override of modes in devices[].modes
            model_tables: dict = model_config.get("tables", {})
            model_modes: dict = model_config.get("modes", {})
            instance_modes_override: dict = device_config.get("modes", {})  # optional per-instance MV switch, etc.
            final_modes: dict = _deep_merge_dicts(model_modes, instance_modes_override)
            device_type: str = device_config["type"]

            device = AsyncGenericModbusDevice(
                model=model,
                client=self.client_dict[port],
                slave_id=slave_id,
                register_type=model_config.get("register_type", "holding"),
                register_map=model_config["register_map"],
                constraint_policy=constraint_policy,
                device_type=device_type,
                table_dict=model_tables,
                mode_dict=final_modes,
                write_hooks=model_config.get("write_hooks", []),
                port_lock=self._port_locks[port],
                port=port,
            )

            self.device_list.append(device)

        # Apply startup frequencies after all devices are initialized
        await self._apply_startup_frequency()

    # TODO: Determine if slave_id should be str or int
    def get_device_by_model_and_slave_id(self, model: str, slave_id: str | int) -> AsyncGenericModbusDevice | None:
        sid = int(slave_id) if isinstance(slave_id, str) else slave_id
        for device in self.device_list:
            if device.model == model and device.slave_id == sid:
                return device
        return None

    async def _apply_startup_frequency(self):
        """Set startup frequency for all devices"""
        if not self.constraint_config_schema:
            logger.warning("No constraint config available, skipping startup frequency setup")
            return

        logger.info("Applying startup frequencies to devices...")

        for device in self.device_list:
            startup_freq = ConfigManager.get_device_startup_frequency(
                self.constraint_config_schema, device.model, device.slave_id
            )

            if startup_freq is not None:
                await self._set_device_startup_frequency(device, startup_freq)
            else:
                logger.debug(f"[{device.model}_{device.slave_id}] No startup frequency configured")

    async def _set_device_startup_frequency(self, device: AsyncGenericModbusDevice, frequency: float):
        """Set the startup frequency for a single device"""
        device_id = f"{device.model}_{device.slave_id}"

        try:
            final_frequency = frequency

            # Check if correction is needed
            if not device.constraints.allow("RW_HZ", frequency):
                hz_constraint: ConstraintConfig | None = device.constraints.constraints.get("RW_HZ")
                if hz_constraint:
                    # Use the constraint minimum as the safe frequency
                    safe_freq = hz_constraint.min if hz_constraint.min is not None else frequency
                    logger.warning(
                        f"[{device_id}] Startup frequency {frequency} Hz outside constraints, "
                        f"using safe minimum value {safe_freq} Hz"
                    )
                    final_frequency = safe_freq

            await device.write_value("RW_HZ", final_frequency)
            logger.info(f"[{device_id}] Set startup frequency to {final_frequency} Hz")

        except Exception as e:
            logger.warning(f"[{device_id}] Failed to set startup frequency: {e}")

    def _is_frequency_within_constraints(self, device: AsyncGenericModbusDevice, frequency: float) -> bool:
        """Check whether the frequency is within the device’s constraint range"""
        return device.constraints.allow("RW_HZ", frequency)

    async def shutdown(self) -> None:
        """Close all underlying Modbus clients and clear cached devices."""

        for client in self.client_dict.values():
            try:
                result = client.close()
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                logger.warning(f"Failed to close Modbus client: {exc}")

        self.client_dict.clear()
        self.device_list.clear()

    async def test_device_connection(self, device_id: str) -> bool:
        """
        Test if a device is online by attempting to read a register.

        Args:
            device_id: Device identifier in format "MODEL_SLAVEID"

        Returns:
            bool: True if device is online, False otherwise
        """
        try:
            model, slave_id_str = device_id.rsplit("_", 1)
            slave_id = int(slave_id_str)
        except ValueError:
            logger.error(f"Invalid device_id format: {device_id}")
            return False

        device = self.get_device_by_model_and_slave_id(model, slave_id)
        if not device:
            logger.warning(f"Device {device_id} not found in device manager")
            return False

        port: str = self._get_device_port(device)
        lock: asyncio.Lock = self._port_locks.get(port)

        try:
            if not device.register_map:
                return False

            first_param = next(iter(device.register_map.keys()))

            if lock:
                async with lock:
                    value = await device.read_value(first_param)
            else:
                value = await device.read_value(first_param)

            return value != DEFAULT_MISSING_VALUE

        except Exception as exc:
            logger.error(f"Connection test failed for {device_id}: {exc}")
            return False

    async def fast_test_device_connection(
        self, device_id: str, test_param_count: int = 5, min_success_rate: float = 0.3
    ) -> tuple[bool, str | None, dict]:
        """
        Fast connection test with reduced timeout and parallel testing.

        Designed for WebSocket connection validation - fails fast if device is offline.

        Args:
            device_id: Device identifier in format "MODEL_SLAVEID"
            test_param_count: Number of parameters to test (default: 5, max: 10)
            min_success_rate: Minimum success rate to pass test (default: 0.3 = 30%)

        Returns:
            Tuple of (success, error_message, details):
            - success: True if device passes test
            - error_message: Reason for failure (None if success)
            - details: Dict with test statistics

        Example:
            >>> success, error, details = await manager.fast_test_device_connection("VFD_01_1")
            >>> print(f"Success: {success}, Details: {details}")
            Success: True, Details: {'tested': 5, 'passed': 5, 'rate': 1.0}
        """
        try:
            # Parse device_id
            model, slave_id_str = device_id.rsplit("_", 1)
            slave_id = int(slave_id_str)
        except ValueError:
            logger.error(f"Invalid device_id format: {device_id}")
            return False, "Invalid device ID format", {}

        # Get device
        device = self.get_device_by_model_and_slave_id(model, slave_id)
        if not device:
            logger.warning(f"Device {device_id} not found in device manager")
            return False, "Device not found", {}

        port: str = self._get_device_port(device)
        lock: asyncio.Lock = self._port_locks.get(port)

        # Get readable parameters
        readable_params = [name for name, cfg in device.register_map.items() if cfg.get("readable", False)]

        if not readable_params:
            logger.error(f"[{device_id}] No readable parameters available for testing")
            return False, "No readable parameters", {}

        # Limit test count
        test_count: int = min(test_param_count, len(readable_params), 10)
        test_param_list: list = readable_params[:test_count]

        logger.info(f"[{device_id}] Fast connection test starting: " f"testing {test_count} parameters")

        # Test parameters with short timeout
        results = []
        start_time = asyncio.get_event_loop().time()

        for param_name in test_param_list:
            try:

                if lock:
                    async with lock:
                        value = await asyncio.wait_for(device.read_value(param_name), timeout=0.8)
                else:
                    value = await asyncio.wait_for(device.read_value(param_name), timeout=0.8)

                is_valid = value != DEFAULT_MISSING_VALUE
                results.append((param_name, is_valid))
            except asyncio.TimeoutError:
                logger.debug(f"[{device_id}] Parameter '{param_name}' timeout")
                results.append((param_name, False))
            except Exception as e:
                logger.debug(f"[{device_id}] Parameter '{param_name}' error: {e}")
                results.append((param_name, False))

        elapsed = asyncio.get_event_loop().time() - start_time

        # Calculate success rate
        passed_count = sum(1 for _, is_valid in results if is_valid)
        success_rate = passed_count / len(results)

        # Prepare details
        details = {
            "tested": len(results),
            "passed": passed_count,
            "failed": len(results) - passed_count,
            "rate": round(success_rate, 2),
            "elapsed_seconds": round(elapsed, 2),
            "parameters": [name for name, _ in results],
            "results": {name: "pass" if valid else "fail" for name, valid in results},
        }

        # Log result
        logger.info(
            f"[{device_id}] Fast connection test completed: "
            f"{passed_count}/{len(results)} passed ({success_rate:.0%}) "
            f"in {elapsed:.2f}s"
        )

        # Check if passed
        if success_rate >= min_success_rate:
            return True, None, details

        error_msg = f"Low response rate: {passed_count}/{len(results)} " f"parameters responded ({success_rate:.0%})"
        return False, error_msg, details

    def _get_device_port(self, device: AsyncGenericModbusDevice) -> str:
        """Get the port for a device."""
        for port, client in self.client_dict.items():
            if device.client == client:
                return port
        return "unknown"
