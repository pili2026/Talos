from core.util.data_decoder import decode_modbus_registers
from core.util.value_util import apply_linear_formula, apply_scale, extract_bit


class ValueDecoder:
    """
    High-level backward-compatible façade.

    New code is recommended to use:
        from util.data_decoder import decode_modbus_registers

    Legacy code:
        ValueDecoder.decode_registers(...)
        ValueDecoder.extract_bit(...)
    remains fully supported.
    """

    @staticmethod
    def decode_registers(fmt: str, registers: list[int]) -> float | int:
        # Simply forward to the low-level decoder (no fast-path logic anymore)
        return decode_modbus_registers(registers, fmt)

    # Legacy passthroughs
    extract_bit = staticmethod(extract_bit)
    apply_scale = staticmethod(apply_scale)
    apply_linear_formula = staticmethod(apply_linear_formula)
