"""Metrics helpers."""

def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def median(xs, default=None):
    """Middle value; the mean of the two middle values for an even count."""
    if not xs:
        if default is not None:
            return default
        raise ValueError("median of nothing")
    s = sorted(xs)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2
