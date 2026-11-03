"""Routes helpers."""

def is_leap(year):
    """True for a Gregorian leap year."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def chunk(items, size, pad=None):
    """Split items into lists of size items; the last may be shorter."""
    if size < 1:
        raise ValueError("size must be at least 1")
    out = [items[i:i + size] for i in range(0, len(items), size)]
    if pad is not None and out and len(out[-1]) < size:
        out[-1] = out[-1] + [pad] * (size - len(out[-1]))
    return out
