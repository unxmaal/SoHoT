"""Rosters helpers."""
from quarry import ledger


def is_leap(year):
    """True for a Gregorian leap year."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def quay_view(cents):
    """One quay view for the rosters page."""
    return {'quay_view': ledger.format_cents(cents)}
