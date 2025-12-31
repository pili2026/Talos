import asyncio
import inspect
import logging
import os

from pymodbus.client import AsyncModbusSerialClient

from core.device.generic.constraints_policy import ConstraintPolicy
from core.device.generic.generic_device import AsyncGenericModbusDevice
from core.model.device_constant import DEFAULT_MISSING_VALUE
from core.schema.constraint_schema import ConstraintConfig, ConstraintConfigSchema
from core.schema.driver_schema import DriverConfig
from core.schema.modbus_device_schema import ModbusDeviceFileConfig
from core.schema.pin_mapping_schema import PinMappingConfig
from core.util.config_manager import ConfigManager
from core.util.config_manager_extension import ConfigManagerExtension
from core.util.pin_mapping_manager import PinMappingManager

logger = logging.getLogger("DeviceManager")


def _deep_merge_dicts(base: dict, override: dict) -> dict:
    """
    Shallow-safe deep merge for 2-level dicts (sufficient for mode tables).

    Rules:
    - If both values are dict -> merge nested
    - Otherwise override wins

    Args:
        base: Base dictionary
        override: Override dictionary

    Returns:
        Merged dictionary
    """
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
    """
    DeviceManager is responsible for:
    - Loading device configurations
    - Building Modbus clients with per-port locks
    - Building devices with cached model configs
    - Three-layer configuration merging (Driver + Pin Mapping + Instance Override)
    - Managing device lifecycle (startup/shutdown)

    Note: Health check, backoff, and cooldown are NOT managed here.
    Those are owned by DeviceHealthManager and AsyncDeviceMonitor.
    """

    def __init__(
        self,
        config_path: str,
        constraint_config_schema: ConstraintConfigSchema,
        model_base_path: str = "./res",
        pin_mapping_base_path: str = "./res/pin_mapping",
    ):
        """
        Initialize AsyncDeviceManager.

        Args:
            config_path: Path to modbus device configuration file
            constraint_config_schema: Device constraint configuration schema
            model_base_path: Base path for device driver YAML files
            pin_mapping_base_path: Base path for pin mapping YAML files
        """
        self.device_list: list[AsyncGenericModbusDevice] = []
        self.client_dict: dict[str, AsyncModbusSerialClient] = {}
        self.config_path = config_path
        self.constraint_config_schema = constraint_config_schema
        self.model_base_path = model_base_path
        self.pin_mapping_manager = PinMappingManager(pin_mapping_base_path)

        # Cached driver configs: model_name -> loaded YAML config
        self.driver_config_by_model: dict[str, dict] = {}

        # Per-port locks for RS-485 serialization: port -> asyncio.Lock
        self._port_locks: dict[str, asyncio.Lock] = {}

    async def init(self) -> None:
        """
        Initialize device connections and build device instances.

        Process:
        1. Load modbus device configuration
        2. For each device:
           a. Load driver config (Layer 1: Hardware)
           b. Load pin mapping (Layer 2: Model-level application)
           c. Get instance pin overrides (Layer 3: Instance-specific)
           d. Merge three layers to build final register map
           e. Create device instance with final config

        Note: Does NOT write startup frequencies.
        Call apply_startup_frequencies_with_health_check() after health check initialization.
        """
        config_raw: dict = ConfigManager().load_yaml_file(self.config_path)
        modbus_device_config = ModbusDeviceFileConfig.model_validate(config_raw)

        for device_config in modbus_device_config.resolve_device_bus_settings():
            if not device_config.port:
                logger.warning(f"Skip device without port: {device_config.model}_{device_config.slave_id}")
                continue

            # Load driver config (Layer 1: Hardware definition)
            model_path: str = os.path.join(self.model_base_path, device_config.model_file)
            model_config_raw: dict = ConfigManager().load_yaml_file(model_path)

            model: str = model_config_raw["model"]
            if model not in self.driver_config_by_model:
                # Cache driver config to avoid re-loading same model file
                self.driver_config_by_model[model] = model_config_raw

            slave_id: int = device_config.slave_id
            port: str = device_config.port
            baudrate: int = int(device_config.baudrate or 9600)
            timeout: float = float(device_config.timeout or 1.0)

            # Create port lock if not exists
            if port not in self._port_locks:
                self._port_locks[port] = asyncio.Lock()

            # Create and connect Modbus client
            if port not in self.client_dict:
                client = AsyncModbusSerialClient(port=port, baudrate=baudrate, timeout=timeout)
                is_connected: bool = await client.connect()
                if not is_connected:
                    logger.warning(f"Failed to connect to port {port}")
                self.client_dict[port] = client

            # Get instance-level constraints
            instance_constraints: dict[str, ConstraintConfig] = ConfigManager.get_instance_constraints_from_schema(
                self.constraint_config_schema, model, slave_id
            )
            constraint_policy = ConstraintPolicy(instance_constraints, logger)

            # Merge model modes with instance-level overrides
            model_tables: dict = model_config_raw.get("tables", {})
            model_modes: dict = model_config_raw.get("modes", {})
            instance_modes_override: dict = device_config.modes or {}
            final_modes: dict = _deep_merge_dicts(model_modes, instance_modes_override)

            device_type: str = device_config.type
            device_id: str = f"{model}_{slave_id}"

            # === Three-Layer Configuration Merging ===

            # Layer 1: Load driver config (hardware definition)
            driver_config = DriverConfig(**model_config_raw)

            # Layer 2: Load pin mapping (model-level application definition)
            try:
                pin_mapping_config: PinMappingConfig = self.pin_mapping_manager.load_pin_mapping(
                    driver_model=model.lower(), mapping_name="default"
                )
                pin_mappings = pin_mapping_config.pin_mappings
            except FileNotFoundError:
                logger.warning(f"[{device_id}] No pin mapping found, using driver defaults only")
                pin_mappings = {}
            except Exception as e:
                logger.error(f"[{device_id}] Failed to load pin mapping: {e}, using driver defaults")
                pin_mappings = {}

            # Layer 3: Get instance-specific pin overrides
            instance_pin_overrides: dict = ConfigManager.get_instance_pins_from_schema(
                self.constraint_config_schema, model, slave_id
            )

            # Merge three layers to build final register map
            final_register_map: dict = ConfigManagerExtension.build_final_register_map(
                driver_register_map=driver_config.register_map,
                pin_mappings=pin_mappings,
                instance_pin_overrides=instance_pin_overrides,
            )

            # Create device instance
            device = AsyncGenericModbusDevice(
                model=model,
                client=self.client_dict[port],
                slave_id=slave_id,
                register_type=model_config_raw.get("register_type", "holding"),
                register_map=final_register_map,
                constraint_policy=constraint_policy,
                device_type=device_type,
                table_dict=model_tables,
                mode_dict=final_modes,
                write_hooks=model_config_raw.get("write_hooks", []),
                port_lock=self._port_locks[port],
                port=port,
                model_config=model_config_raw,
            )

            self.device_list.append(device)

        logger.info("Device connections ready (startup frequencies will be applied after health check initialization)")

    def get_device_by_model_and_slave_id(self, model: str, slave_id: str | int) -> AsyncGenericModbusDevice | None:
        """
        Get device instance by model name and slave ID.

        Args:
            model: Device model name
            slave_id: Slave ID (int or string)

        Returns:
            Device instance if found, None otherwise
        """
        sid = int(slave_id) if isinstance(slave_id, str) else slave_id
        for device in self.device_list:
            if device.model == model and device.slave_id == sid:
                return device
        return None

    def _is_frequency_within_constraints(self, device: AsyncGenericModbusDevice, frequency: float) -> bool:
        """
        Check whether the frequency is within the device's constraint range.

        Args:
            device: Device instance
            frequency: Frequency to check in Hz

        Returns:
            True if within constraints, False otherwise
        """
        return device.constraints.allow("RW_HZ", frequency)

    async def shutdown(self) -> None:
        """
        Close all underlying Modbus clients and clear cached devices.
        """
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

        Note:
        - Do NOT acquire port lock here
        - ModbusBus already serializes I/O using the shared per-port lock
        - Double-lock will cause deadlock (asyncio.Lock is not re-entrant)

        Args:
            device_id: Device ID in format "MODEL_SLAVEID"

        Returns:
            True if device responds, False otherwise
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

        try:
            if not device.register_map:
                return False

            first_param = next(iter(device.register_map.keys()))
            value = await device.read_value(first_param)
            return value != DEFAULT_MISSING_VALUE

        except Exception as exc:
            logger.error(f"Connection test failed for {device_id}: {exc}")
            return False

    async def fast_test_device_connection(
        self,
        device_id: str,
        test_param_count: int = 5,
        min_success_rate: float = 0.3,
    ) -> tuple[bool, str | None, dict]:
        """
        Fast connection test with reduced timeout.

        Note:
        - Do NOT acquire port lock here
        - ModbusBus already serializes I/O using the shared per-port lock
        - Double-lock will cause deadlock (asyncio.Lock is not re-entrant)

        Args:
            device_id: Device ID in format "MODEL_SLAVEID"
            test_param_count: Number of parameters to test (max 10)
            min_success_rate: Minimum success rate to consider device online

        Returns:
            Tuple of (is_online, error_message, details_dict)
        """
        try:
            model, slave_id_str = device_id.rsplit("_", 1)
            slave_id = int(slave_id_str)
        except ValueError:
            logger.error(f"Invalid device_id format: {device_id}")
            return False, "Invalid device ID format", {}

        device = self.get_device_by_model_and_slave_id(model, slave_id)
        if not device:
            logger.warning(f"Device {device_id} not found in device manager")
            return False, "Device not found", {}

        readable_params = [name for name, cfg in device.register_map.items() if cfg.get("readable", False)]
        if not readable_params:
            logger.error(f"[{device_id}] No readable parameters available for testing")
            return False, "No readable parameters", {}

        test_count: int = min(test_param_count, len(readable_params), 10)
        test_param_list: list[str] = readable_params[:test_count]

        logger.info(f"[{device_id}] Fast connection test starting: testing {test_count} parameters")

        results: list[tuple[str, bool]] = []
        loop = asyncio.get_event_loop()
        start_time = loop.time()

        for param_name in test_param_list:
            try:
                value = await asyncio.wait_for(device.read_value(param_name), timeout=0.8)
                is_valid = value != DEFAULT_MISSING_VALUE
                results.append((param_name, is_valid))
            except asyncio.TimeoutError:
                logger.debug(f"[{device_id}] Parameter '{param_name}' timeout")
                results.append((param_name, False))
            except Exception as exc:
                logger.debug(f"[{device_id}] Parameter '{param_name}' error: {exc}")
                results.append((param_name, False))

        elapsed = loop.time() - start_time

        passed_count = sum(1 for _, is_valid in results if is_valid)
        success_rate = passed_count / len(results)

        details = {
            "tested": len(results),
            "passed": passed_count,
            "failed": len(results) - passed_count,
            "rate": round(success_rate, 2),
            "elapsed_seconds": round(elapsed, 2),
            "parameters": [name for name, _ in results],
            "results": {name: "pass" if valid else "fail" for name, valid in results},
        }

        logger.info(
            f"[{device_id}] Fast connection test completed: "
            f"{passed_count}/{len(results)} passed ({success_rate:.0%}) "
            f"in {elapsed:.2f}s"
        )

        if success_rate >= min_success_rate:
            return True, None, details

        error_msg = f"Low response rate: {passed_count}/{len(results)} parameters responded " f"({success_rate:.0%})"
        return False, error_msg, details

    def _get_device_port(self, device: AsyncGenericModbusDevice) -> str:
        """
        Get the port for a device.

        Args:
            device: Device instance

        Returns:
            Port path string
        """
        for port, client in self.client_dict.items():
            if device.client == client:
                return port
        return "unknown"

    def _device_key(self, device: AsyncGenericModbusDevice) -> str:
        """
        Generate device key string.

        Args:
            device: Device instance

        Returns:
            Device key in format "MODEL_SLAVEID"
        """
        return f"{device.model}_{device.slave_id}"
