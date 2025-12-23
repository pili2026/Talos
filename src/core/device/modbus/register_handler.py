import logging

from core.device.generic.modbus_bus import ModbusBus
from core.device.modbus.device_helper import required_word_count
from core.model.device_constant import DEFAULT_MISSING_VALUE, HI_SHIFT, INVALID_U16_SENTINEL, MD_SHIFT
from core.util.data_decoder import DecodeFormat
from core.util.value_decoder import ValueDecoder


class ModbusRegisterHandler:
    """
    Handles low-level Modbus register read/write operations.
    Supports multi-word formats, bit operations, and invalid value detection.
    """

    def __init__(self, model: str, register_map: dict, bus: ModbusBus, logger: logging.Logger):
        self.model = model
        self.register_map = register_map
        self.bus = bus
        self.logger = logger
        self.decoder = ValueDecoder()

    async def read_raw(self, reg_config: dict) -> float | int:
        """Read raw value(s) from Modbus according to register configuration."""
        if reg_config.get("composed_of"):
            return await self._read_composed(reg_config)

        fmt: str | DecodeFormat = reg_config.get("format", DecodeFormat.U16)
        word_count: int = required_word_count(fmt)

        try:
            registers = await self.bus.read_regs(reg_config["offset"], word_count)
            if not isinstance(registers, (list, tuple)) or len(registers) < word_count:
                self.logger.error(f"[{self.model}] read_regs returned insufficient words for {fmt}: {registers}")
                return DEFAULT_MISSING_VALUE

            register_words: list[int] = [int(w) & INVALID_U16_SENTINEL for w in registers[:word_count]]
            if self.is_invalid_raw(reg_config, register_words):
                self.logger.debug(
                    f"[{self.model}] Invalid raw value detected for offset={reg_config.get('offset')}: {register_words}"
                )
                return DEFAULT_MISSING_VALUE
        except Exception as e:
            self.logger.exception(
                f"[{self.model}] read_regs failed at offset={reg_config.get('offset')} fmt={fmt}: {e}"
            )
            return DEFAULT_MISSING_VALUE

        return self.decoder.decode_registers(fmt, list(registers))

    async def write_word(self, offset: int, raw_value: int) -> None:
        """Write a 16-bit word to a register."""
        await self.bus.write_u16(offset, int(raw_value))

    async def write_bit(self, offset: int, bit_index: int, bit_value: int) -> int | None:
        """Write a single bit using read-modify-write."""
        try:
            current = await self.bus.read_u16(offset)
        except Exception as e:
            self.logger.warning(f"[{self.model}] Read before bit-write failed (offset={offset}): {e}")
            return None

        new_word = int(current)
        if bit_value:
            new_word |= 1 << bit_index
        else:
            new_word &= ~(1 << bit_index)

        try:
            await self.bus.write_u16(offset, new_word)
            return new_word
        except Exception as e:
            self.logger.warning(
                f"[{self.model}] Bit-write failed (offset={offset}): {e}. "
                f"Attempted: {current:#06x} -> {new_word:#06x}"
            )
            return None

    def is_invalid_raw(self, pin_cfg: dict, words: list[int]) -> bool:
        """Detect sentinel values for invalid readings."""
        if not words:
            return True

        words = [int(w) & INVALID_U16_SENTINEL for w in words]

        invalid_raw_words = pin_cfg.get("invalid_raw_words")
        if isinstance(invalid_raw_words, list):
            for pattern in invalid_raw_words:
                if isinstance(pattern, (list, tuple)) and list(pattern) == words:
                    return True

        if len(words) == 1:
            invalid_raw = pin_cfg.get("invalid_raw")
            if isinstance(invalid_raw, list):
                return words[0] in {int(x) & INVALID_U16_SENTINEL for x in invalid_raw}

        if len(words) == 1:
            return words[0] == INVALID_U16_SENTINEL
        if len(words) == 2:
            return words[0] == INVALID_U16_SENTINEL and words[1] == INVALID_U16_SENTINEL

        return False

    async def _read_composed(self, reg_config: dict) -> int:
        """Read 48-bit composed value from three 16-bit registers."""
        sub_registers = reg_config["composed_of"]
        if not isinstance(sub_registers, (list, tuple)) or len(sub_registers) != 3:
            self.logger.error(f"[{self.model}] Invalid composed_of={sub_registers}, must have exactly 3 entries")
            return DEFAULT_MISSING_VALUE

        register_value_list: list[int] = []
        for sub_key in sub_registers:
            pin_cfg = self.register_map.get(sub_key) or {}
            if "offset" not in pin_cfg:
                self.logger.error(f"[{self.model}] composed_of sub key '{sub_key}' missing 'offset'")
                return DEFAULT_MISSING_VALUE
            word = await self.bus.read_u16(pin_cfg["offset"])
            register_value_list.append(int(word) & INVALID_U16_SENTINEL)

        hi, md, lo = register_value_list
        return (hi << HI_SHIFT) | (md << MD_SHIFT) | lo
