def to_int(x):
    try:
        return int(float(x))
    except Exception:
        return 0


def to_float(x):
    try:
        return float(x)
    except Exception:
        return 0.0


def apply_decimal_places(
    raw_value: float | None, decimal_places: int | None, *, max_decimal_places: int = 9
) -> float | None:
    """
    Convert a raw integer value using DEC (number of decimal places):
        value = raw / (10 ** dec)

    - If raw or dec is missing → return None
    - If dec < 0 → skip (treat as invalid)
    - Avoid overflow from extremely large 10**dec
    """
    if raw_value is None or decimal_places is None:
        return None
    try:
        decimal_places_int = int(decimal_places)
        if decimal_places_int < 0 or decimal_places_int > max_decimal_places:
            return None
        return float(raw_value) / (10**decimal_places_int)
    except Exception:
        return None


def combine_32bit_be(reg0: int | None, reg1: int | None) -> int | None:
    """
    Combine two 16-bit registers into a 32-bit value (Big Endian byte order).

    In Big Endian:
        - reg0 (lower address) contains the HIGH word
        - reg1 (higher address) contains the LOW word

    Formula:
        value = (reg0 << 16) | reg1

    Equivalent to:
        value = reg0 * 65536 + reg1

    Args:
        reg0: High 16-bit word at lower register address (0~65535)
        reg1: Low 16-bit word at higher register address (0~65535)

    Returns:
        The combined 32-bit unsigned value (0~4294967295).
        Returns None if either input is None.

    Examples:
        >>> combine_32bit_be(0, 12345)
        12345
        >>> combine_32bit_be(1, 34463)
        99999
        >>> combine_32bit_be(0xFFFF, 0xFFFF)
        4294967295
    """
    if reg0 is None or reg1 is None:
        return None
    return (reg0 << 16) | reg1


def combine_32bit_le(reg0: int | None, reg1: int | None) -> int | None:
    """
    Combine two 16-bit registers into a 32-bit value (Little Endian byte order).

    In Little Endian:
        - reg0 (lower address) contains the LOW word
        - reg1 (higher address) contains the HIGH word

    Formula:
        value = (reg1 << 16) | reg0

    Note:
        The register order is reversed compared to Big Endian.
        Little Endian stores the least significant word at the lower address.

    Args:
        reg0: Low 16-bit word at lower register address (0~65535)
        reg1: High 16-bit word at higher register address (0~65535)

    Returns:
        The combined 32-bit unsigned value (0~4294967295).
        Returns None if either input is None.

    Examples:
        >>> combine_32bit_le(12345, 0)
        12345
        >>> combine_32bit_le(34463, 1)
        99999
    """
    if reg0 is None or reg1 is None:
        return None
    return (reg1 << 16) | reg0


def combine_32bit_signed_be(reg0: int | None, reg1: int | None) -> int | None:
    """
    Combine two 16-bit registers into a signed 32-bit value (Big Endian byte order).

    In Big Endian:
        - reg0 (lower address) contains the HIGH word
        - reg1 (higher address) contains the LOW word

    Signed 32-bit range:
        -2147483648 ~ 2147483647

    Args:
        reg0: High 16-bit word at lower register address (0~65535)
        reg1: Low 16-bit word at higher register address (0~65535)

    Returns:
        A signed 32-bit integer.
        Returns None if either input is None.

    Examples:
        >>> combine_32bit_signed_be(0, 12345)
        12345
        >>> combine_32bit_signed_be(0xFFFF, 0xFFFF)
        -1
    """
    if reg0 is None or reg1 is None:
        return None
    val = (reg0 << 16) | reg1
    # Convert to signed (the highest bit indicates the sign)
    if val > 0x7FFFFFFF:  # 2^31 - 1
        val -= 0x100000000  # 2^32
    return val


def combine_32bit_signed_le(reg0: int | None, reg1: int | None) -> int | None:
    """
    Combine two 16-bit registers into a signed 32-bit value (Little Endian byte order).

    In Little Endian:
        - reg0 (lower address) contains the LOW word
        - reg1 (higher address) contains the HIGH word

    Signed 32-bit range:
        -2147483648 ~ 2147483647

    Formula:
        value = (reg1 << 16) | reg0

    Note:
        The register order is reversed compared to Big Endian.

    Args:
        reg0: Low 16-bit word at lower register address (0~65535)
        reg1: High 16-bit word at higher register address (0~65535)

    Returns:
        A signed 32-bit integer.
        Returns None if either input is None.

    Examples:
        >>> combine_32bit_signed_le(12345, 0)
        12345
        >>> combine_32bit_signed_le(0xFFFF, 0xFFFF)
        -1
        >>> combine_32bit_signed_le(0xFFFE, 0xFFFF)
        -2
    """
    if reg0 is None or reg1 is None:
        return None
    val = (reg1 << 16) | reg0
    # Convert to signed (the highest bit indicates the sign)
    if val > 0x7FFFFFFF:  # 2^31 - 1
        val -= 0x100000000  # 2^32
    return val
