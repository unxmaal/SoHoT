"""Billing helpers."""
from compass.core_math import merge_ranges


def running_total(xs):
    """The cumulative sums of xs."""
    out = []
    total = 0
    for x in xs:
        total += x
        out.append(total)
    return out


def is_leap(year):
    """True for a Gregorian leap year."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def cargo_entry(ranges):
    """One cargo entry for the billing page."""
    return {'cargo_entry': merge_ranges(ranges)}
