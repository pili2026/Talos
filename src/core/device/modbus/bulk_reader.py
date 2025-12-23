import logging
from dataclasses import dataclass
from typing import Any

from core.device.modbus.device_helper import required_word_count
from core.model.device_constant import DEFAULT_MISSING_VALUE, INVALID_U16_SENTINEL
from core.model.enum.register_type_enum import RegisterType
from core.util.data_decoder import DecodeFormat
from core.util.value_decoder import ValueDecoder


@dataclass(frozen=True)
class BulkRange:
    """Represents a contiguous range of registers for bulk reading."""

    register_type: str
    start: int
    count: int
    items: list[tuple[str, dict]]  # (pin_name, cfg)


class ModbusBulkReader:
    """
    Handles bulk reading optimization for Modbus devices.
    Groups contiguous registers into single read operations.
    """

    def __init__(self, register_map: dict, default_register_type: str, logger: logging.Logger):
        self.register_map = register_map
        self.default_register_type = default_register_type
        self.logger = logger
        self.decoder = ValueDecoder()

    def build_bulk_ranges(self, max_regs_per_req: int = 120) -> list[BulkRange]:
        """Build list of contiguous register ranges for bulk reading."""
        bulk_candidates: list[tuple[str, dict, int, int, str]] = []

        for pin_name, pin_cfg in self.register_map.items():
            if not self._is_bulk_eligible(pin_cfg):
                continue

            register_type = pin_cfg.get("register_type", self.default_register_type)
            start_offset = int(pin_cfg.get("offset"))
            decode_format = pin_cfg.get("format", DecodeFormat.U16)
            word_count = required_word_count(decode_format)

            bulk_candidates.append((pin_name, pin_cfg, start_offset, word_count, register_type))

        bulk_candidates.sort(key=lambda c: (c[4], c[2]))
        return self._merge_candidates_into_ranges(bulk_candidates, max_regs_per_req)

    def process_bulk_range_result(
        self, bulk_range: BulkRange, registers: list[int], is_invalid_raw_func: callable
    ) -> dict[str, Any]:
        """Process bulk read results and map back to pins."""
        result: dict[str, Any] = {}

        for pin_name, pin_cfg in bulk_range.items:
            try:
                pin_offset = int(pin_cfg["offset"])
            except Exception:
                result[pin_name] = DEFAULT_MISSING_VALUE
                continue

            decode_format = pin_cfg.get("format", DecodeFormat.U16)
            word_count = required_word_count(decode_format)

            relative_index = pin_offset - bulk_range.start
            if relative_index < 0:
                result[pin_name] = DEFAULT_MISSING_VALUE
                continue

            register_words = registers[relative_index : relative_index + word_count]
            if len(register_words) < word_count:
                result[pin_name] = DEFAULT_MISSING_VALUE
                continue

            register_words = [int(w) & INVALID_U16_SENTINEL for w in register_words]
            if is_invalid_raw_func(pin_cfg, register_words):
                result[pin_name] = DEFAULT_MISSING_VALUE
                continue

            decoded_value = self.decoder.decode_registers(decode_format, register_words)
            final_value = self._apply_post_process(pin_cfg, decoded_value)
            result[pin_name] = final_value

        return result

    def _is_bulk_eligible(self, config_raw: dict) -> bool:
        """Check if a pin configuration is eligible for bulk reading."""
        if not config_raw.get("readable"):
            return False
        if config_raw.get("register_type") in {RegisterType.COIL.value, RegisterType.DISCRETE_INPUT.value}:
            return False
        if config_raw.get("composed_of"):
            return False
        if config_raw.get("scale_from"):
            return False
        pin_rt = config_raw.get("register_type", self.default_register_type)
        return pin_rt in {RegisterType.HOLDING.value, RegisterType.INPUT.value, self.default_register_type}

    def _merge_candidates_into_ranges(
        self, candidates: list[tuple[str, dict, int, int, str]], max_regs: int
    ) -> list[BulkRange]:
        """Merge bulk candidates into contiguous ranges."""
        bulk_ranges: list[BulkRange] = []

        current_register_type: str | None = None
        current_range_start: int = 0
        current_range_end: int = 0
        current_range_pins: list[tuple[str, dict]] = []

        for pin_name, pin_cfg, start_offset, word_count, register_type in candidates:
            next_range_start = start_offset
            next_range_end = start_offset + word_count

            if current_register_type is None:
                current_register_type = register_type
                current_range_start = next_range_start
                current_range_end = next_range_end
                current_range_pins = [(pin_name, pin_cfg)]
                continue

            should_split = (
                register_type != current_register_type
                or next_range_start != current_range_end
                or (next_range_end - current_range_start) > max_regs
            )

            if should_split:
                bulk_ranges.append(
                    BulkRange(
                        register_type=current_register_type,
                        start=current_range_start,
                        count=current_range_end - current_range_start,
                        items=current_range_pins,
                    )
                )
                current_register_type = register_type
                current_range_start = next_range_start
                current_range_end = next_range_end
                current_range_pins = [(pin_name, pin_cfg)]
                continue

            current_range_end = next_range_end
            current_range_pins.append((pin_name, pin_cfg))

        if current_register_type is not None:
            bulk_ranges.append(
                BulkRange(
                    register_type=current_register_type,
                    start=current_range_start,
                    count=current_range_end - current_range_start,
                    items=current_range_pins,
                )
            )

        return bulk_ranges

    def _apply_post_process(self, config: dict, value: int | float) -> int | float:
        """Apply post-processing steps to decoded value."""
        if config.get("bit") is not None:
            value = self.decoder.extract_bit(value, config["bit"])

        if config.get("formula"):
            value = self.decoder.apply_linear_formula(value, config["formula"])

        value = self.decoder.apply_scale(value, config.get("scale", 1.0))

        precision: int = config.get("precision")
        if precision:
            value = round(value, precision)

        return value
