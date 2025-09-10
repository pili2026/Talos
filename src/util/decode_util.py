from enum import StrEnum

from pymodbus.client.mixin import ModbusClientMixin


class NumericFormat(StrEnum):
    FLOAT32 = "float32"
    UINT32 = "uint32"
    INT16 = "int16"
    UINT16 = "uint16"
    U16 = "u16"
    U32 = "u32"
    F32 = "f32"


def decode_numeric_by_format(raw: list[int], fmt: NumericFormat) -> float | int:
    match fmt:
        case NumericFormat.FLOAT32:
            return ModbusClientMixin.convert_from_registers(
                raw, word_order="big", data_type=ModbusClientMixin.DATATYPE.FLOAT32
            )
        case NumericFormat.UINT32:
            return ModbusClientMixin.convert_from_registers(
                raw, word_order="little", data_type=ModbusClientMixin.DATATYPE.UINT32
            )
        case NumericFormat.INT16:
            return ModbusClientMixin.convert_from_registers(
                raw, word_order="little", data_type=ModbusClientMixin.DATATYPE.INT16
            )
        case NumericFormat.UINT16:
            return ModbusClientMixin.convert_from_registers(
                raw, word_order="little", data_type=ModbusClientMixin.DATATYPE.UINT16
            )
        case _:
            return raw[0]
