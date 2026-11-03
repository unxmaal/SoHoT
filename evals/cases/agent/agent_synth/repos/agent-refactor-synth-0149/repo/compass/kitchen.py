"""Kitchen helpers."""
from compass import tickets


def format_cents(cents):
    """Cents as dollars with thousands separators, such as -$1,234.56."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def harbor_view(ranges):
    """One harbor view for the kitchen page."""
    return {'harbor_view': tickets.merge_ranges(ranges)}
