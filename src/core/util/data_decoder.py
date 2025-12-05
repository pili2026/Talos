from typing import Union

from pymodbus.client.mixin import ModbusClientMixin

from core.model.enum.decode_format import DecodeFormat


def decode_modbus_registers(raw: list[int], fmt: Union[DecodeFormat, str]) -> float | int:
    """
    Decode a list of 16-bit Modbus registers into a numeric value according to the given format.

    Supported formats:
        - u16             → 16-bit unsigned integer
        - i16             → 16-bit signed integer
        - u32_le / u32_be → 32-bit unsigned integer (explicit word order)
        - f32_le / f32_be → 32-bit float (explicit word order)
        - f32_be_swap     → 32-bit float with word-swap (BADC byte order)

    Notes:
        * Word order = sequence of 16-bit registers (not internal byte order)
        * 'little' means the low word comes first (e.g., DAE_PM210 uses u32_le)
        * 'f32_be_swap' swaps words before big-endian decode (DO750 O2 format)
    """
    # Normalize to enum
    if isinstance(fmt, str):
        fmt_enum = DecodeFormat.from_string(fmt)
        if fmt_enum is None:
            return raw[0] if raw else 0
        fmt: DecodeFormat = fmt_enum

    # Decode using match-case
    match fmt:
        # ===== 32-bit Unsigned Integer =====
        case DecodeFormat.U32 | DecodeFormat.U32_LE:
            return ModbusClientMixin.convert_from_registers(
                raw, word_order="little", data_type=ModbusClientMixin.DATATYPE.UINT32
            )

        case DecodeFormat.U32_BE:
            return ModbusClientMixin.convert_from_registers(
                raw, word_order="big", data_type=ModbusClientMixin.DATATYPE.UINT32
            )

        # ===== 32-bit Float =====
        case DecodeFormat.F32 | DecodeFormat.F32_BE:
            return ModbusClientMixin.convert_from_registers(
                raw, word_order="big", data_type=ModbusClientMixin.DATATYPE.FLOAT32
            )

        case DecodeFormat.F32_LE:
            return ModbusClientMixin.convert_from_registers(
                raw, word_order="little", data_type=ModbusClientMixin.DATATYPE.FLOAT32
            )

        case DecodeFormat.F32_BE_SWAP:
            # DO750 O2 format: word-swap then big-endian
            if len(raw) < 2:
                return 0.0
            swapped = [raw[1], raw[0]]
            return ModbusClientMixin.convert_from_registers(
                swapped, word_order="big", data_type=ModbusClientMixin.DATATYPE.FLOAT32
            )

        # ===== 16-bit Integers =====
        case DecodeFormat.I16:
            return ModbusClientMixin.convert_from_registers(
                raw, word_order="little", data_type=ModbusClientMixin.DATATYPE.INT16
            )

        case DecodeFormat.U16:
            return ModbusClientMixin.convert_from_registers(
                raw, word_order="little", data_type=ModbusClientMixin.DATATYPE.UINT16
            )

        # ===== Fallback =====
        case _:
            return raw[0] if raw else 0
