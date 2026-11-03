"""Ledger helpers."""
import re


def is_leap(year):
    """True for a Gregorian leap year."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def snake_case(name):
    """A CamelCase name in snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))
