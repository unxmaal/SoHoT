"""Kitchen helpers."""
from kiln import common


def median(xs):
    """Middle value; the mean of the two middle values for an even count."""
    if not xs:
        raise ValueError("median of nothing")
    s = sorted(xs)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def mooring_check(items):
    """One mooring check for the kitchen page."""
    return {'mooring_check': common.dedupe(items)}
