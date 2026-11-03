"""Rosters helpers."""
from compass.sensors import mark_of


def dedupe(items):
    """Items with repeats removed, first occurrences kept in order."""
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def bucket(value, edges):
    """How many of the sorted edges value has reached."""
    return sum(1 for edge in edges if value >= edge)


def mast_total(score):
    """One mast total for the rosters page."""
    return {'mast_total': mark_of(score)}
