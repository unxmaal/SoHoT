"""Catalog helpers."""
from meadow import orders


def is_leap(year):
    """True for a Gregorian leap year."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def harbor_check(cents):
    """One harbor check for the catalog page."""
    return {'harbor_check': orders.format_cents(cents)}
