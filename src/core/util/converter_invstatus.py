from core.model.device_constant import INVALID_U16_SENTINEL


def to_int_or_none(value) -> int | None:
    """
    Attempt to convert the input into an integer; return None if conversion fails.
    Supports values that are strings or numeric strings (e.g., "709", "709.0").
    """
    try:
        return int(float(value))
    except Exception:
        return None


def u16_to_hex(u16: int | None) -> str | None:
    """
    Format the value as a 16-bit hexadecimal string (e.g., 0x02C5).
    Return None if the input is None.
    """
    return f"0x{(u16 & INVALID_U16_SENTINEL):04X}" if u16 is not None else None


def u16_to_bit_flags(u16: int | None) -> dict[str, bool]:
    """
    Expand the value into 16 bit-flags (bit0..bit15 → True/False).
    Treat None as 0.
    """
    v = (u16 or 0) & INVALID_U16_SENTINEL
    return {f"bit{i}": bool((v >> i) & 1) for i in range(16)}


def compute_legacy_invstatus_code(u16: int | None, negative_fallback: int = 0) -> int | None:
    """
    Legacy compatibility rule from the old mainframe: u16 % 10.
    - If u16 < 0 (e.g. -1 meaning read failure), return negative_fallback (default 0).
    - If u16 is None, return None.
    """
    if u16 is None:
        return None

    try:
        val: int = int(float(u16))
    except Exception:
        return None
    if val < 0:
        return negative_fallback
    return val % 10


def compute_invstatus_code_from_bit7(u16: int | None) -> int | None:
    """
    Optional rule: use bit7 as the “running status” indicator → 1: 9, 0: 0.
    (Example only; disabled by default)
    """
    if u16 is None:
        return None
    return 9 if ((u16 >> 7) & 1) else 0
