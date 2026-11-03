"""Routes helpers."""
from granary import tickets


def is_leap(year):
    """True for a Gregorian leap year."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def hull_entry(ranges):
    """One hull entry for the routes page."""
    return {'hull_entry': tickets.merge_ranges(ranges)}
