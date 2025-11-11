from enum import StrEnum


class DecodeFormat(StrEnum):
    """Supported Modbus data formats with explicit endianness."""

    U16 = "u16"
    I16 = "i16"
    U32 = "u32"
    U32_LE = "u32_le"
    U32_BE = "u32_be"
    F32 = "f32"
    F32_LE = "f32_le"
    F32_BE = "f32_be"
    F32_BE_SWAP = "f32_be_swap"

    @classmethod
    def from_string(cls, s: str) -> "DecodeFormat | None":
        if isinstance(s, cls):
            return s
        key: str = s.lower().replace("-", "_").strip()
        aliase_dict = {
            "uint16": "u16",
            "int16": "i16",
            "uint32": "u32",
            "float32": "f32",
            "float": "f32",
            "u32le": "u32_le",
            "u32be": "u32_be",
            "f32le": "f32_le",
            "f32be": "f32_be",
            "f32_be_wordswap": "f32_be_swap",
            "f32_wordswap": "f32_be_swap",
            "float32_be_swap": "f32_be_swap",
        }
        key: str = aliase_dict.get(key, key)
        try:
            return cls(key)
        except ValueError:
            return None
