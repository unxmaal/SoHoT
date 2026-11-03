"""Rosters helpers."""
from lantern import ledger


def format_cents(cents):
    """Cents as dollars with thousands separators, such as -$1,234.56."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def tide_row(items, page, per_page):
    """One tide row for the rosters page."""
    return {'tide_row': ledger.paginate(items, page, per_page)}
