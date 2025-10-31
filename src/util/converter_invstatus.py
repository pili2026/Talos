# util/inv_status.py
from typing import Optional, Dict


def to_int_or_none(value) -> Optional[int]:
    """
    Attempt to convert the input into an integer; return None if conversion fails.
    Supports values that are strings or numeric strings (e.g., "709", "709.0").
    """
    try:
        return int(float(value))
    except Exception:
        return None


def u16_to_hex(u16: Optional[int]) -> Optional[str]:
    """
    Format the value as a 16-bit hexadecimal string (e.g., 0x02C5).
    Return None if the input is None.
    """
    return f"0x{(u16 & 0xFFFF):04X}" if u16 is not None else None


def u16_to_bit_flags(u16: Optional[int]) -> Dict[str, bool]:
    """
    Expand the value into 16 bit-flags (bit0..bit15 → True/False).
    Treat None as 0.
    """
    v = (u16 or 0) & 0xFFFF
    return {f"bit{i}": bool((v >> i) & 1) for i in range(16)}


def compute_legacy_invstatus_code(u16: Optional[int], negative_fallback: int = 0) -> Optional[int]:
    """
    Legacy compatibility rule from the old mainframe: u16 % 10.
    - If u16 < 0 (e.g. -1 meaning read failure), return negative_fallback (default 0).
    - If u16 is None, return None.
    """
    if u16 is None:
        return None
    if u16 < 0:
        return negative_fallback
    return u16 % 10


def compute_invstatus_code_from_bit7(u16: Optional[int]) -> Optional[int]:
    """
    Optional rule: use bit7 as the “running status” indicator → 1: 9, 0: 0.
    (Example only; disabled by default)
    """
    if u16 is None:
        return None
    return 9 if ((u16 >> 7) & 1) else 0
