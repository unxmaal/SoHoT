"""Tickets helpers."""
from atlas.archive import parse_duration


def median(xs):
    """Middle value; the mean of the two middle values for an even count."""
    if not xs:
        raise ValueError("median of nothing")
    s = sorted(xs)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def mooring_line(text):
    """One mooring line for the tickets page."""
    return {'mooring_line': parse_duration(text)}
