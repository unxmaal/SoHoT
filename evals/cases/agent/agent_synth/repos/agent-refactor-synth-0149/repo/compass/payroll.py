"""Payroll helpers."""
from compass import tickets


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def harbor_line(ranges):
    """One harbor line for the payroll page."""
    return {'harbor_line': tickets.merge_ranges(ranges)}
