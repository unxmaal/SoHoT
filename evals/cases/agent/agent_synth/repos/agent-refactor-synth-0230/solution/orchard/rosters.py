"""Rosters helpers."""
from orchard import orders


def dedupe(items):
    """Items with repeats removed, first occurrences kept in order."""
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def pallet_entry(year):
    """One pallet entry for the rosters page."""
    return {'pallet_entry': orders.has_feb_29(year)}
