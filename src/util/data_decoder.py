from enum import StrEnum
from typing import Union

from pymodbus.client.mixin import ModbusClientMixin


class DataFormat(StrEnum):
    """Supported Modbus data formats with explicit endianness."""

    U16 = "u16"
    I16 = "i16"
    U32_LE = "u32_le"
    U32_BE = "u32_be"
    F32_LE = "f32_le"
    F32_BE = "f32_be"


def decode_modbus_registers(raw: list[int], fmt: Union[DataFormat, str]) -> float | int:
    """
    Decode a list of 16-bit Modbus registers into a numeric value according to the given format.

    Supported formats:
        - u16             → 16-bit unsigned integer
        - i16             → 16-bit signed integer
        - u32_le / u32_be → 32-bit unsigned integer (explicit word order)
        - f32_le / f32_be → 32-bit float (explicit word order)

    Notes:
        * Word order = sequence of 16-bit registers (not internal byte order)
        * 'little' means the low word comes first (e.g., DAE_PM210 uses u32_le)
    """
    f = fmt.value if isinstance(fmt, DataFormat) else str(fmt).lower()

    # ---------- 32-bit Unsigned Integer ----------
    if f in ("u32", "u32_le", "uint32"):
        return ModbusClientMixin.convert_from_registers(
            raw, word_order="little", data_type=ModbusClientMixin.DATATYPE.UINT32
        )
    if f == "u32_be":
        return ModbusClientMixin.convert_from_registers(
            raw, word_order="big", data_type=ModbusClientMixin.DATATYPE.UINT32
        )

    # ---------- 32-bit Float ----------
    if f in ("f32", "f32_be", "float32"):
        return ModbusClientMixin.convert_from_registers(
            raw, word_order="big", data_type=ModbusClientMixin.DATATYPE.FLOAT32
        )
    if f == "f32_le":
        return ModbusClientMixin.convert_from_registers(
            raw, word_order="little", data_type=ModbusClientMixin.DATATYPE.FLOAT32
        )

    # ---------- 16-bit Integers ----------
    if f == "i16":
        return ModbusClientMixin.convert_from_registers(
            raw, word_order="little", data_type=ModbusClientMixin.DATATYPE.INT16
        )
    if f == "u16":
        return ModbusClientMixin.convert_from_registers(
            raw, word_order="little", data_type=ModbusClientMixin.DATATYPE.UINT16
        )

    # ---------- Fallback ----------
    return raw[0]
