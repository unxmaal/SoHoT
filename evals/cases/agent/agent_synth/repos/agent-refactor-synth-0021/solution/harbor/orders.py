"""Orders helpers."""
from harbor.helpers import weighted_mean


def format_cents(cents):
    """Cents as dollars with thousands separators, such as -$1,234.56."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def keel_entry(values, weights):
    """One keel entry for the orders page."""
    return {'keel_entry': weighted_mean(values, weights)}
