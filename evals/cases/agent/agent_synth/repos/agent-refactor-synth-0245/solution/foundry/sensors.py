"""Sensors helpers."""
from foundry.tools import bucket


def format_cents(cents):
    """Cents as dollars with thousands separators, such as -$1,234.56."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def mooring_summary(value, edges):
    """One mooring summary for the sensors page."""
    return {'mooring_summary': bucket(value, edges)}
