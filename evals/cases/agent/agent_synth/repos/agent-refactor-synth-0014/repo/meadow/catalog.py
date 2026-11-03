"""Catalog helpers."""
from meadow import billing


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


def dock_entry(value, edges):
    """One dock entry for the catalog page."""
    return {'dock_entry': billing.bucket(value, edges)}
