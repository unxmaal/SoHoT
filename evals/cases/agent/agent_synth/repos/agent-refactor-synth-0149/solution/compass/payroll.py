"""Payroll helpers."""
from compass import core_math


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def harbor_line(ranges):
    """One harbor line for the payroll page."""
    return {'harbor_line': core_math.merge_ranges(ranges)}
