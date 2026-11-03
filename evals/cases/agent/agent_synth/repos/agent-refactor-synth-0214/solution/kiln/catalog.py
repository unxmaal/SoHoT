"""Catalog helpers."""

def has_feb_29(year):
    """True for a Gregorian leap year."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
