import logging
from typing import Any

from core.device.generic.generic_device import AsyncGenericModbusDevice
from core.executor.control_executor import ControlExecutor
from core.model.enum.device_constant_enum import DeviceConstantEnum
from core.schema.constraint_schema import ConstraintConfigSchema, InitializationConfig
from core.schema.control_condition_schema import ControlActionSchema, ControlActionType
from core.util.device_health_manager import DeviceHealthManager
from core.util.pubsub.base import PubSub
from core.util.pubsub.pubsub_topic import PubSubTopic

logger = logging.getLogger("InitializationSubscriber")


class InitializationSubscriber:
    """
    Automatic device initialization on offline->online transition.

    Responsibilities:
    - Detect device recovery (offline -> online)
    - Apply startup frequency configuration
    - Conditionally turn on device (respecting Time Control)

    Behavior:
    - Always sets startup_frequency (if configured)
    - Only turns on if:
      * auto_turn_on is enabled, AND
      * No Time Control OR within working hours

    Integration:
    - Subscribes to DEVICE_SNAPSHOT (raw snapshots with is_online flag)
    - Respects Time Control constraints via TimeControlEvaluator
    - Uses health check to verify device stability before init

    Priority:
    - Uses init_priority (default: 50, lower than Control Condition)
    - Allows Control Condition to override if needed
    """

    def __init__(
        self,
        *,
        pubsub: PubSub,
        executor: ControlExecutor,
        constraint_schema: ConstraintConfigSchema,
        health_manager: DeviceHealthManager | None = None,
        init_priority: int = 50,
    ) -> None:
        """
        Initialize InitializationSubscriber.

        Args:
            pubsub: Message bus for subscribing to device snapshots
            executor: Control executor for sending commands to devices
            constraint_schema: Device configuration including initialization settings
            health_manager: Optional health manager for stability checks
            time_control_evaluator: Optional Time Control evaluator for working hours
            init_priority: Priority for initialization actions (default: 50)
        """
        self.pubsub = pubsub
        self.executor = executor
        self.constraint_schema = constraint_schema
        self.health_manager = health_manager
        self.init_priority = init_priority

        # Track last known online state for each device
        # Used to detect offline->online transitions
        self._last_online: dict[str, bool] = {}

    async def run(self) -> None:
        """
        Main subscriber loop.

        Subscribes to DEVICE_SNAPSHOT topic and processes each snapshot
        to detect device recovery events.

        Note: Subscribes to DEVICE_SNAPSHOT (not SNAPSHOT_ALLOWED) because:
        - DEVICE_SNAPSHOT contains is_online flag
        - SNAPSHOT_ALLOWED only contains snapshots within Time Control hours
        - We need to detect recovery at any time, then check Time Control ourselves
        """
        logger.info(f"[INIT] Subscribing to {PubSubTopic.DEVICE_SNAPSHOT}")

        async for snap in self.pubsub.subscribe(PubSubTopic.DEVICE_SNAPSHOT):
            try:
                await self._handle_snapshot(snap)
            except Exception as e:
                logger.warning(f"[INIT] Error handling snapshot: {e}", exc_info=True)

    async def _handle_snapshot(self, snap: dict[str, Any]) -> None:
        """
        Handle device snapshot and trigger initialization on offline->online transition.

        Logic:
        1. Detect offline->online transition
        2. Verify device health (optional)
        3. Resolve initialization config
        4. Execute initialization actions (SET_FREQUENCY + optional TURN_ON)

        Note: Does NOT check Time Control here. TimeControlHandler will enforce
        time restrictions separately if needed.
        """
        device_id = snap.get("device_id")

        if not device_id:
            return

        # Track online state to detect transitions
        now_online = bool(snap.get("is_online", False))
        was_online = self._last_online.get(device_id, False)
        self._last_online[device_id] = now_online

        # Only process offline->online transitions
        if was_online or not now_online:
            return

        logger.info(f"[INIT] Detected offline->online transition: {device_id}")

        # Extract device identifiers
        model: str = snap.get("model")
        slave_id: int | str = snap.get("slave_id")
        if not model or slave_id is None:
            logger.warning(f"[INIT] [{device_id}] Missing model/slave_id in snapshot, skip initialization")
            return

        slave_id = str(slave_id)
        model_slave = f"{model}_{slave_id}"

        # Step 1: Get device instance from device manager (required)
        device: AsyncGenericModbusDevice | None = self.executor.device_manager.get_device_by_model_and_slave_id(
            model, slave_id
        )
        if not device:
            logger.warning(f"[INIT] [{model_slave}] Device not found in device_manager, skip initialization")
            return

        # Step 2: Optional health check before initialization
        # Ensures device is stable and ready for initialization commands
        if self.health_manager:
            try:
                is_ok, health_result = await self.health_manager.quick_health_check(
                    device=device, device_id=model_slave
                )
                elapsed_ms: float = float(health_result.elapsed_ms) if health_result else 0.0

                if not is_ok:
                    logger.info(
                        f"[INIT] [{model_slave}] Health check failed ({elapsed_ms:.0f}ms), "
                        f"skip initialization (device may be unstable)"
                    )
                    return

                logger.info(f"[INIT] [{model_slave}] Health check passed ({elapsed_ms:.0f}ms)")

            except Exception as exc:
                logger.warning(
                    f"[INIT] [{model_slave}] Health check error: {exc}, "
                    f"skip initialization (cannot verify device stability)"
                )
                return

        # Step 3: Resolve initialization configuration
        # Uses hierarchical config: global_defaults -> model -> instance
        init_config: InitializationConfig | None = self._resolve_initialization(model=model, slave_id=slave_id)
        if not init_config:
            logger.debug(f"[INIT] [{model_slave}] No initialization config found, skip")
            return

        # Step 4: Build initialization actions
        actions: list[ControlActionSchema] = []

        # Action 1: SET_FREQUENCY (always execute if configured)
        # Sets target frequency regardless of Time Control
        # This prepares the device for operation when allowed
        if init_config.startup_frequency is not None:
            actions.append(
                ControlActionSchema(
                    type=ControlActionType.SET_FREQUENCY,
                    model=model,
                    slave_id=slave_id,
                    target=DeviceConstantEnum.REG_RW_HZ.value,
                    value=float(init_config.startup_frequency),
                    priority=self.init_priority,
                    reason=f"[INIT] Recovery: set RW_HZ={init_config.startup_frequency}",
                )
            )
            logger.debug(f"[INIT] [{model_slave}] Will set frequency to {init_config.startup_frequency} Hz")

        # Action 2: TURN_ON (conditional, respects Time Control)
        if init_config.auto_turn_on:
            actions.append(
                ControlActionSchema(
                    type=ControlActionType.TURN_ON,
                    model=model,
                    slave_id=slave_id,
                    target=None,  # ControlExecutor already handles target for TURN_ON
                    value=None,  # ControlExecutor already handles target for TURN_ON
                    priority=self.init_priority,
                    reason="[INIT] Recovery: turn_on",
                )
            )

        # Step 5: Execute actions if any
        if not actions:
            logger.debug(f"[INIT] [{model_slave}] No initialization actions to execute")
            return

        # Log action summary before execution
        action_summary = [(a.type.value, a.target, a.value) for a in actions]
        logger.info(f"[INIT] [{model_slave}] Executing {len(actions)} initialization action(s): " f"{action_summary}")

        try:
            await self.executor.execute(actions)
            logger.info(f"[INIT] [{model_slave}] Initialization completed successfully")
        except Exception as exc:
            logger.error(f"[INIT] [{model_slave}] Failed to execute initialization actions: {exc}", exc_info=True)

    def _resolve_initialization(self, *, model: str, slave_id: str) -> InitializationConfig | None:
        """
        Resolve initialization configuration with hierarchical precedence.

        Precedence (higher priority overrides lower):
        1. Instance level: devices[model].instances[slave_id].initialization
        2. Model level: devices[model].initialization
        3. Global level: global_defaults.initialization

        Args:
            model: Device model name
            slave_id: Device slave ID (as string)

        Returns:
            Merged InitializationConfig or None if no config found
        """
        merged: dict[str, Any] = {}

        # Level 1: Global defaults
        if self.constraint_schema.global_defaults and self.constraint_schema.global_defaults.initialization:
            merged.update(self.constraint_schema.global_defaults.initialization.model_dump(exclude_none=True))

        # Level 2: Model defaults
        dev = self.constraint_schema.devices.get(model)
        if dev and dev.initialization:
            merged.update(dev.initialization.model_dump(exclude_none=True))

        # Level 3: Instance specific
        if dev and dev.instances:
            inst = dev.instances.get(str(slave_id))
            if inst and inst.initialization:
                merged.update(inst.initialization.model_dump(exclude_none=True))

        if not merged:
            return None

        # Validate and construct InitializationConfig from merged dict
        try:
            return InitializationConfig(**merged)
        except Exception as e:
            logger.warning(f"[INIT] Invalid initialization config for {model}_{slave_id}: {e}")
            return None
