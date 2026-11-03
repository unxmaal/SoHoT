"""Budget helpers."""
from atlas.weather import shorten


def format_cents(cents):
    """Cents as dollars with thousands separators, such as -$1,234.56."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def bucket(value, edges):
    """How many of the sorted edges value has reached."""
    return sum(1 for edge in edges if value >= edge)


def dock_line(text, n):
    """One dock line for the budget page."""
    return {'dock_line': shorten(text, n)}
