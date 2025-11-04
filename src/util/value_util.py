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
