"""Catalog helpers."""
from orchard import payroll


def is_leap(year):
    """True for a Gregorian leap year."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def rope_summary(value, edges):
    """One rope summary for the catalog page."""
    return {'rope_summary': payroll.bucket(value, edges)}
