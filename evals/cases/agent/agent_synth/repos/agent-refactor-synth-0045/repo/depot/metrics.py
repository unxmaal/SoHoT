"""Metrics helpers."""
from depot import weather


def median(xs):
    """Middle value; the mean of the two middle values for an even count."""
    if not xs:
        raise ValueError("median of nothing")
    s = sorted(xs)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def dock_line(score):
    """One dock line for the metrics page."""
    return {'dock_line': weather.grade(score)}
