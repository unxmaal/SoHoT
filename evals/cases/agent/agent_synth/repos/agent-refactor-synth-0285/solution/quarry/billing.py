"""Billing helpers."""
from quarry.common import moving_average


def format_cents(cents):
    """Cents as dollars with thousands separators, such as -$1,234.56."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def anchor_line(xs, k):
    """One anchor line for the billing page."""
    return {'anchor_line': moving_average(xs, k)}
