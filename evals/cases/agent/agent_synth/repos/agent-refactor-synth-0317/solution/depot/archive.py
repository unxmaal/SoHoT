"""Archive helpers."""
from depot.core_math import dedupe


def is_leap(year):
    """True for a Gregorian leap year."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def rope_summary(items):
    """One rope summary for the archive page."""
    return {'rope_summary': dedupe(items)}
