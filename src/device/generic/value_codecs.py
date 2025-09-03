from util.decode_util import NumericFormat, decode_numeric_by_format


class ValueDecoder:
    @staticmethod
    def decode_words(fmt, words: list[int]) -> float | int:
        f = ""
        # Fast path for common formats
        if isinstance(fmt, str):
            f = fmt.lower()
        if f in ("u16", "uint16"):
            return int(words[0])
        if f in ("i16", "int16"):
            raw = int(words[0]) & 0xFFFF
            return raw - 0x10000 if (raw & 0x8000) else raw
        if f in ("u32", "uint32"):
            return decode_numeric_by_format(words, NumericFormat.UINT32)
        if f in ("f32", "float32"):
            return decode_numeric_by_format(words, NumericFormat.FLOAT32)
        # Backward compatible path
        return decode_numeric_by_format(words, fmt)

    @staticmethod
    def apply_bit(value: int | float, bit: int) -> int:
        return (int(value) >> bit) & 1

    @staticmethod
    def apply_formula(value: float | int, formula: tuple[float, float, float]) -> float:
        n1, n2, n3 = formula
        return (float(value) + float(n1)) * float(n2) + float(n3)

    @staticmethod
    def apply_scale(value: float | int, scale: float) -> float:
        return float(value) * float(scale)
