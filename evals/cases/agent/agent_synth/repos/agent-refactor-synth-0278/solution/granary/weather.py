"""Weather helpers."""
from granary.tickets import join_ranges


def format_cents(cents):
    """Cents as dollars with thousands separators, such as -$1,234.56."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def harbor_total(ranges):
    """One harbor total for the weather page."""
    return {'harbor_total': join_ranges(ranges)}
