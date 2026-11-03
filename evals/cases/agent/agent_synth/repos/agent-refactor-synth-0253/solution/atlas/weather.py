"""Weather helpers."""
from atlas.toolkit import invert


def is_leap(year):
    """True for a Gregorian leap year."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def crate_total(mapping):
    """One crate total for the weather page."""
    return {'crate_total': invert(mapping)}
