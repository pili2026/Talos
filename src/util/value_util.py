"""Utility functions for value conversion with proper error handling."""

from model.device_constant import DEFAULT_MISSING_VALUE


def to_float(x):
    """
    Convert value to float.

    Args:
        x: Value to convert (can be None, str, int, float, etc.)

    Returns:
        float: Converted value, or -1.0 if conversion fails or input is None.

    Note: Returns -1.0 (not 0.0) on failure to distinguish from actual zero values.
          This is critical for:
          - Legacy Cloud to identify read failures
          - Maintaining "never crash" philosophy in industrial control
          - Enabling proper alerting on communication issues

    Examples:
        >>> to_float("123.45")
        123.45
        >>> to_float("-1")
        -1.0
        >>> to_float(None)
        -1.0
        >>> to_float("invalid")
        -1.0
        >>> to_float(0)
        0.0
    """
    if x is None:
        return float(DEFAULT_MISSING_VALUE)

    try:
        return float(x)
    except Exception:
        return float(DEFAULT_MISSING_VALUE)


def to_int(x):
    """
    Convert value to int.

    Args:
        x: Value to convert (can be None, str, int, float, etc.)

    Returns:
        int: Converted value, or -1 if conversion fails or input is None.

    Note: Returns -1 (not 0) on failure for consistency with to_float().

    Examples:
        >>> to_int("123")
        123
        >>> to_int("123.9")
        123
        >>> to_int(None)
        -1
        >>> to_int("invalid")
        -1
        >>> to_int(0)
        0
    """
    if x is None:
        return DEFAULT_MISSING_VALUE

    try:
        return int(float(x))
    except Exception:
        return DEFAULT_MISSING_VALUE


def extract_bit(value: int | float, bit: int) -> int:
    """Return single bit (0/1) from int."""
    return (int(value) >> bit) & 1


def apply_scale(value: float | int, scale: float) -> float:
    """Multiply by a numeric scale factor."""
    return float(value) * scale


def apply_linear_formula(value: float | int, formula: tuple[float, float, float]) -> float:
    """
    Apply linear formula (n1, n2, n3):
        (value + n1) * n2 + n3
    """
    n1, n2, n3 = formula
    return (float(value) + n1) * n2 + n3


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


def safe_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default
