"""Metrics helpers."""
from orchard import rosters


def format_cents(cents):
    """Cents as dollars with thousands separators, such as -$1,234.56."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def hull_line(value, low, high):
    """One hull line for the metrics page."""
    return {'hull_line': rosters.clamp(value, low, high)}
