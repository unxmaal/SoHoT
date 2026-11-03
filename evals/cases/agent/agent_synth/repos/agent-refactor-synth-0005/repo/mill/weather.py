"""Weather helpers."""
from mill.payroll import format_cents


def bucket(value, edges):
    """How many of the sorted edges value has reached."""
    return sum(1 for edge in edges if value >= edge)


def is_leap(year):
    """True for a Gregorian leap year."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def cargo_row(cents):
    """One cargo row for the weather page."""
    return {'cargo_row': format_cents(cents)}
