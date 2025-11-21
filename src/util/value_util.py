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
