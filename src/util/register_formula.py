"""
Register combination formulas for computed fields.
Provides functions to combine multiple 16-bit registers into larger values.
"""

from typing import Callable


def combine_32bit_be(reg0: int | float | None, reg1: int | float | None) -> int | None:
    """
    Combine two 16-bit registers into a 32-bit value (Big Endian byte order).

    In Big Endian:
        - reg0 (lower address) contains the HIGH word
        - reg1 (higher address) contains the LOW word

    Formula:
        value = (reg0 << 16) | reg1

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

    # Convert to int (device may return float values)
    r0 = int(reg0) & 0xFFFF
    r1 = int(reg1) & 0xFFFF

    return (r0 << 16) | r1


def combine_32bit_le(reg0: int | float | None, reg1: int | float | None) -> int | None:
    """
    Combine two 16-bit registers into a 32-bit value (Little Endian byte order).

    In Little Endian:
        - reg0 (lower address) contains the LOW word
        - reg1 (higher address) contains the HIGH word

    Formula:
        value = (reg1 << 16) | reg0

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

    # Convert to int (device may return float values)
    r0 = int(reg0) & 0xFFFF
    r1 = int(reg1) & 0xFFFF

    return (r1 << 16) | r0


def combine_32bit_signed_be(reg0: int | float | None, reg1: int | float | None) -> int | None:
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

    # Convert to int (device may return float values)
    r0 = int(reg0) & 0xFFFF
    r1 = int(reg1) & 0xFFFF

    val = (r0 << 16) | r1

    # Convert to signed (the highest bit indicates the sign)
    if val > 0x7FFFFFFF:  # 2^31 - 1
        val -= 0x100000000  # 2^32
    return val


def combine_32bit_signed_le(reg0: int | float | None, reg1: int | float | None) -> int | None:
    """
    Combine two 16-bit registers into a signed 32-bit value (Little Endian byte order).

    In Little Endian:
        - reg0 (lower address) contains the LOW word
        - reg1 (higher address) contains the HIGH word

    Signed 32-bit range:
        -2147483648 ~ 2147483647

    Formula:
        value = (reg1 << 16) | reg0

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

    # Convert to int (device may return float values)
    r0 = int(reg0) & 0xFFFF
    r1 = int(reg1) & 0xFFFF

    val = (r1 << 16) | r0

    # Convert to signed (the highest bit indicates the sign)
    if val > 0x7FFFFFFF:  # 2^31 - 1
        val -= 0x100000000  # 2^32
    return val


# Formula Registry - maps formula names to functions
FORMULA_REGISTRY: dict[str, Callable] = {
    "combine_32bit_be": combine_32bit_be,
    "combine_32bit_le": combine_32bit_le,
    "combine_32bit_signed_be": combine_32bit_signed_be,
    "combine_32bit_signed_le": combine_32bit_signed_le,
}


def get_formula(name: str) -> Callable | None:
    """
    Get a formula function by name.

    Args:
        name: Formula name (e.g., "combine_32bit_be")

    Returns:
        Formula function or None if not found.
    """
    return FORMULA_REGISTRY.get(name)


def register_formula(name: str, func: Callable) -> None:
    """
    Register a new formula function.

    Args:
        name: Formula name
        func: Formula function
    """
    FORMULA_REGISTRY[name] = func
