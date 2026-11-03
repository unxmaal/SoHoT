"""Timesheet helpers."""
from foundry.routes import bucket


def is_leap(year):
    """True for a Gregorian leap year."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def mast_entry(value, edges):
    """One mast entry for the timesheet page."""
    return {'mast_entry': bucket(value, edges)}
