"""
Virtual Device Manager

Manages virtual devices that aggregate data from multiple physical devices.
Currently supports: aggregated power meters.

Key behaviors:
- Aggregates data from multiple physical devices based on configuration
- Supports sum, avg, max, min aggregation methods
- Special handling for Power Factor calculation (Kw / Kva)
- Fail-fast error handling: if any source fails, result is -1
- Virtual devices appear identical to physical devices downstream

Example:
    Two ADTEK_CPM10 power meters (slave_id 1, 2) measuring split power lines
    → Virtual device (slave_id 3) shows aggregated totals
"""

import logging
from datetime import datetime

from core.schema.virtual_device_schema import (
    AggregatedFieldConfig,
    AggregationMethod,
    ErrorHandling,
    SourceConfig,
    VirtualDeviceConfig,
    VirtualDevicesConfigSchema,
)
from device_manager import AsyncDeviceManager

logger = logging.getLogger("VirtualDeviceManager")


class VirtualDeviceManager:
    """
    Manages virtual devices that aggregate data from physical devices.

    Virtual devices:
    - Are computed from raw device snapshots
    - Have the same format as physical devices
    - Are automatically included in DEVICE_SNAPSHOT events
    - Are stored in SQLite snapshot storage
    - Are sent to cloud via Legacy Sender
    """

    def __init__(
        self,
        config: VirtualDevicesConfigSchema,
        device_manager: AsyncDeviceManager,
    ):
        """
        Initialize Virtual Device Manager

        Args:
            config: Virtual device configuration schema
            device_manager: AsyncDeviceManager for accessing physical devices
        """
        self.config = config
        self.device_manager = device_manager
        self.enabled_devices: list[VirtualDeviceConfig] = []
        self._initialize()

    def _initialize(self):
        """Initialize enabled virtual devices"""
        for virtual_device in self.config.virtual_devices:
            if virtual_device.enabled:
                self.enabled_devices.append(virtual_device)
                logger.debug(
                    f"[VirtualDeviceManager] Registered virtual device: {virtual_device.id} "
                    f"(type={virtual_device.type}, source={virtual_device.source.model}, "
                    f"target={virtual_device.target.model}_{virtual_device.target.slave_id})"
                )

        if not self.enabled_devices:
            logger.info("[VirtualDeviceManager] No virtual devices enabled")
        else:
            logger.info(
                f"[VirtualDeviceManager] Initialized with {len(self.enabled_devices)} " f"enabled virtual device(s)"
            )

    def compute_virtual_snapshots(
        self,
        raw_snapshots: dict[str, dict],
    ) -> dict[str, dict]:
        """
        Compute virtual device snapshots from raw device data.

        This is the main entry point called by AsyncDeviceMonitor after
        polling physical devices.

        Args:
            raw_snapshots: Dictionary of {device_id: snapshot_dict}
                          from physical devices

        Returns:
            Dictionary of {virtual_device_id: virtual_snapshot_dict}

        Example:
            raw_snapshots = {
                "ADTEK_CPM10_1": {
                    "device_id": "ADTEK_CPM10_1",
                    "model": "ADTEK_CPM10",
                    "slave_id": 1,
                    "sampling_ts": datetime(...),
                    "values": {"Kw": 100, "Kva": 120, ...}
                },
                "ADTEK_CPM10_2": {...}
            }

            Result:
            {
                "ADTEK_CPM10_3": {
                    "device_id": "ADTEK_CPM10_3",
                    "model": "ADTEK_CPM10",
                    "slave_id": 3,
                    "sampling_ts": datetime(...),
                    "values": {"Kw": 250, "Kva": 300, ...},
                    "_is_virtual": True,
                    ...
                }
            }
        """
        if not self.enabled_devices:
            return {}

        virtual_snapshots = {}

        for vdev in self.enabled_devices:
            try:
                virtual_snap = self._compute_single_virtual_device(vdev, raw_snapshots)

                if virtual_snap:
                    device_id = virtual_snap["device_id"]
                    virtual_snapshots[device_id] = virtual_snap
                    logger.debug(
                        f"[VirtualDeviceManager] Computed virtual device: {device_id} "
                        f"from {len(virtual_snap.get('_source_device_ids', []))} source(s)"
                    )

            except Exception as e:
                logger.error(
                    f"[VirtualDeviceManager] Failed to compute virtual device '{vdev.id}': {e}",
                    exc_info=True,
                )

        return virtual_snapshots

    def _compute_single_virtual_device(
        self,
        virtual_device_config: VirtualDeviceConfig,
        raw_snapshots: dict[str, dict],
    ) -> dict | None:
        """
        Compute a single virtual device snapshot.

        Steps:
        1. Find source devices
        2. Compute target slave_id
        3. Aggregate fields
        4. Calculate Power Factor (if needed)
        5. Build virtual snapshot

        Args:
            vdev: Virtual device configuration
            raw_snapshots: Raw device snapshots

        Returns:
            Virtual device snapshot dict, or None if cannot compute
        """
        if virtual_device_config.type != "aggregated_power_meter":
            logger.error(f"[VirtualDeviceManager] Unknown virtual device type: {virtual_device_config.type}")
            return None

        # Find source devices
        source_device_id_list: list[str] = self._find_source_devices(virtual_device_config.source, raw_snapshots)

        if not source_device_id_list:
            logger.warning(
                f"[{virtual_device_config.id}] No source devices found "
                f"(model={virtual_device_config.source.model}, slave_ids={virtual_device_config.source.slave_ids})"
            )
            return None

        logger.info(
            f"[{virtual_device_config.id}] Found {len(source_device_id_list)} source device(s): "
            f"{source_device_id_list}"
        )

        # Compute target slave_id
        target_slave_id: int = self._compute_target_slave_id(
            virtual_device_config.target.slave_id,
            source_device_id_list,
        )

        # Aggregate fields
        aggregated_values = {}
        all_failed = True  # Track if all fields failed

        for field_config in virtual_device_config.aggregation.fields:
            if field_config.method == AggregationMethod.CALCULATED_PF:
                # Skip calculated fields in first pass
                continue

            result: float = self._aggregate_field(
                field_config=field_config,
                source_device_ids=source_device_id_list,
                raw_snapshots=raw_snapshots,
                error_handling=virtual_device_config.aggregation.error_handling,
            )

            aggregated_values[field_config.name] = result

            if result != -1:
                all_failed = False

        # Calculate Power Factor (if specified)
        for field_config in virtual_device_config.aggregation.fields:
            if field_config.method == AggregationMethod.CALCULATED_PF:
                pf_result = self._calculate_power_factor(
                    field_name=field_config.name,
                    aggregated_values=aggregated_values,
                )
                aggregated_values[field_config.name] = pf_result

                if pf_result != -1:
                    all_failed = False

        # Log warning if all fields failed
        if all_failed:
            logger.warning(
                f"[{virtual_device_config.id}] All aggregated fields failed, " f"creating snapshot with -1 values"
            )

        # Build virtual snapshot
        virtual_device_id: str = f"{virtual_device_config.target.model}_{target_slave_id}"

        sampling_ts: datetime | None = self._get_latest_sampling_ts(source_device_id_list, raw_snapshots)

        virtual_snapshot = {
            "device_id": virtual_device_id,
            "model": virtual_device_config.target.model,
            "slave_id": target_slave_id,
            "type": "power_meter",
            "sampling_ts": sampling_ts,
            "values": aggregated_values,
            # Metadata for debugging and tracking
            "_is_virtual": True,
            "_virtual_config_id": virtual_device_config.id,
            "_source_device_ids": source_device_id_list,
            "_description": virtual_device_config.description,
        }

        return virtual_snapshot

    def _find_source_devices(
        self,
        source_config: SourceConfig,
        raw_snapshots: dict[str, dict],
    ) -> list[str]:
        """
        Find source devices based on source configuration.

        Logic:
        - If slave_ids is None or empty list [] → aggregate ALL devices of this model
        - If slave_ids is [1, 2] → aggregate only devices with slave_id 1 and 2

        Args:
            source_config: Source configuration
            raw_snapshots: Raw device snapshots

        Returns:
            List of device_ids (e.g., ["ADTEK_CPM10_1", "ADTEK_CPM10_2"])
        """
        source_device_ids = []

        for device_id, snapshot in raw_snapshots.items():
            # Skip other virtual devices
            if snapshot.get("_is_virtual", False):
                continue

            # Parse device_id (format: MODEL_SLAVEID)
            try:
                model, slave_id_str = device_id.rsplit("_", 1)
                slave_id = int(slave_id_str)
            except (ValueError, AttributeError):
                logger.warning(f"[VirtualDeviceManager] Invalid device_id format: {device_id}")
                continue

            # Check model match
            if model != source_config.model:
                continue

            # Check slave_id filter
            if source_config.slave_ids is not None and len(source_config.slave_ids) > 0:
                # Explicit list specified → only include these slave_ids
                if slave_id not in source_config.slave_ids:
                    continue

            # Either no filter (None or []) or slave_id matches filter
            source_device_ids.append(device_id)

        return sorted(source_device_ids)  # Sort for deterministic ordering

    def _compute_target_slave_id(
        self,
        target_slave_id_config: str | int,
        source_device_ids: list[str],
    ) -> int:
        """
        Compute target slave_id for the virtual device.

        Logic:
        - If "auto" → max(all_devices_slave_ids) + 1 (across entire bus)
        - If explicit integer → use that value

        Args:
            target_slave_id_config: "auto" or explicit integer
            source_device_ids: List of source device IDs (unused but kept for API)

        Returns:
            Computed slave_id as integer
        """
        if target_slave_id_config != "auto":
            return int(target_slave_id_config)

        # Auto: max(all_devices_slave_ids) + 1
        # Scan all devices in AsyncDeviceManager to find max slave_id
        max_slave_id = 0

        for device in self.device_manager.device_list:
            max_slave_id: str | int = max(max_slave_id, device.slave_id)

        computed_id = max_slave_id + 1

        logger.debug(
            f"[VirtualDeviceManager] Auto-computed target slave_id: {computed_id} "
            f"(max across all devices: {max_slave_id})"
        )

        return computed_id

    def _aggregate_field(
        self,
        field_config: AggregatedFieldConfig,
        source_device_ids: list[str],
        raw_snapshots: dict[str, dict],
        error_handling: ErrorHandling,
    ) -> float:
        """
        Aggregate a single field across source devices.

        Args:
            field_config: Field configuration (name, method)
            source_device_ids: List of source device IDs
            raw_snapshots: Raw snapshot data
            error_handling: Error handling strategy

        Returns:
            Aggregated value, or -1 if failed
        """
        field_name = field_config.name
        method = field_config.method

        values = []
        has_failure = False

        # Collect values from all source devices
        for device_id in source_device_ids:
            snapshot = raw_snapshots.get(device_id, {})
            value = snapshot.get("values", {}).get(field_name, -1)

            if value == -1:
                has_failure = True
                logger.warning(f"[VirtualDeviceManager] Field '{field_name}' read failed " f"from {device_id}")

                if error_handling == ErrorHandling.FAIL_FAST:
                    logger.info(
                        f"[VirtualDeviceManager] Aggregation failed for '{field_name}' "
                        f"due to {device_id} failure (fail_fast mode)"
                    )
                    return -1
                # PARTIAL mode: continue with available values
            else:
                values.append(value)

        if not values:
            logger.warning(f"[VirtualDeviceManager] No valid values for '{field_name}', " f"returning -1")
            return -1

        # Perform aggregation based on method
        try:
            match method:
                case AggregationMethod.SUM:
                    result = sum(values)
                case AggregationMethod.AVG:
                    result = sum(values) / len(values)
                case AggregationMethod.MAX:
                    result = max(values)
                case AggregationMethod.MIN:
                    result = min(values)
                case _:
                    logger.error(f"[VirtualDeviceManager] Unknown aggregation method: {method}")
                    return -1

            if has_failure and error_handling == ErrorHandling.PARTIAL:
                logger.info(
                    f"[VirtualDeviceManager] Partial aggregation for '{field_name}': "
                    f"{result:.2f} from {len(values)}/{len(source_device_ids)} devices"
                )

            return result

        except Exception as e:
            logger.error(f"[VirtualDeviceManager] Aggregation failed for '{field_name}': {e}")
            return -1

    def _calculate_power_factor(
        self,
        field_name: str,
        aggregated_values: dict[str, float],
    ) -> float:
        """
        Calculate Power Factor from aggregated Kw and Kva.

        Power Factor = Kw / Kva

        This must be calculated from totals, NOT averaged from individual PFs!

        Example:
            meter1: Kw=100, Kva=120, PF=0.833
            meter2: Kw=150, Kva=180, PF=0.833

            Correct:   PF_total = (100+150)/(120+180) = 250/300 = 0.833
            Incorrect: PF_total = (0.833+0.833)/2 = 0.833 (coincidentally same)

        Args:
            field_name: Field name (typically "AveragePowerFactor")
            aggregated_values: Already aggregated values (must include Kw and Kva)

        Returns:
            Calculated power factor, or -1 if cannot calculate
        """
        kw: float = aggregated_values.get("Kw", -1)
        kva: float = aggregated_values.get("Kva", -1)

        # Check if dependencies are valid
        if kw == -1 or kva == -1:
            logger.warning(f"[VirtualDeviceManager] Cannot calculate {field_name}: " f"Kw or Kva is -1 (failed read)")
            return -1

        # Check for division by zero
        if kva == 0:
            logger.warning(f"[VirtualDeviceManager] Cannot calculate {field_name}: " f"Kva is 0 (division by zero)")
            return 0  # Return 0 when Kva is 0

        pf = kw / kva

        # Power factor should be between -1 and 1
        if abs(pf) > 1:
            logger.warning(f"[VirtualDeviceManager] Abnormal {field_name} calculated: {pf:.3f}, " f"capping to ±1")
            return 1.0 if pf > 0 else -1.0

        logger.info(f"[VirtualDeviceManager] Calculated {field_name}: {pf:.3f} " f"(Kw={kw:.2f}, Kva={kva:.2f})")

        return pf

    def _get_latest_sampling_ts(
        self,
        source_device_ids: list[str],
        raw_snapshots: dict[str, dict],
    ) -> datetime | None:
        """
        Get the latest sampling timestamp from source devices.

        Uses max() to represent "this aggregated value is based on the
        most recent data we have".

        Args:
            source_device_ids: List of source device IDs
            raw_snapshots: Raw device snapshots

        Returns:
            Latest timestamp, or None if no timestamps found
        """
        timestamps = []

        for device_id in source_device_ids:
            snapshot = raw_snapshots.get(device_id, {})
            ts = snapshot.get("sampling_ts")
            if ts:
                timestamps.append(ts)

        if not timestamps:
            logger.warning("[VirtualDeviceManager] No sampling timestamps found in source devices")
            return None

        return max(timestamps)  # Use the latest timestamp
