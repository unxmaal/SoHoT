"""Billing helpers."""

def is_leap(year):
    """True for a Gregorian leap year."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def format_cents(cents, symbol="$"):
    """Cents as dollars with thousands separators, such as -$1,234.56."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{symbol}{cents // 100:,}.{cents % 100:02d}"
