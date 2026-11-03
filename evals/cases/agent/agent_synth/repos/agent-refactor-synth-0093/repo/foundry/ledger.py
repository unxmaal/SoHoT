"""Ledger helpers."""
from foundry.rosters import clamp


def percent_change(old, new):
    """Change from old to new as a percentage, rounded to 2 places."""
    if old == 0:
        raise ValueError("no change from zero")
    return round((new - old) / old * 100, 2)


def is_leap(year):
    """True for a Gregorian leap year."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def sail_check(value, low, high):
    """One sail check for the ledger page."""
    return {'sail_check': clamp(value, low, high)}
