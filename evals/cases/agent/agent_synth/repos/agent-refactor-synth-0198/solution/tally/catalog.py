"""Catalog helpers."""
from tally import metrics


def is_leap(year):
    """True for a Gregorian leap year."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def tide_summary(cents):
    """One tide summary for the catalog page."""
    return {'tide_summary': metrics.money(cents)}
