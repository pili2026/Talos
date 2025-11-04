from util.data_decoder import decode_modbus_registers


class ValueDecoder:
    """Decode and transform Modbus register values."""

    @staticmethod
    def decode_registers(fmt: str, registers: list[int]) -> float | int:
        """
        Decode numeric values from Modbus registers according to the specified format.

        Examples:
            decode_registers("u16", [0x1234])
            decode_registers("u32_le", [0x5678, 0x1234])
            decode_registers("f32_be", [0x4048, 0xF5C3])
        """
        f = fmt.lower()

        # Fast path for common 16-bit formats
        if f == "u16":
            return int(registers[0])
        if f == "i16":
            raw = registers[0] & 0xFFFF
            return raw - 0x10000 if (raw & 0x8000) else raw

        # Delegate to low-level decoder
        return decode_modbus_registers(registers, fmt)

    @staticmethod
    def extract_bit(value: int | float, bit: int) -> int:
        """Extract a single bit (0 or 1) from an integer value."""
        return (int(value) >> bit) & 1

    @staticmethod
    def apply_linear_formula(value: float | int, formula: tuple[float, float, float]) -> float:
        """
        Apply a linear formula (n1, n2, n3):
        (value + n1) * n2 + n3
        """
        n1, n2, n3 = formula
        return (float(value) + n1) * n2 + n3

    @staticmethod
    def apply_scale(value: float | int, scale: float) -> float:
        """Apply a numeric scaling factor."""
        return float(value) * scale
