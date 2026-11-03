"""Sensors helpers."""
from compass import kitchen


def dedupe(items):
    """Items with repeats removed, first occurrences kept in order."""
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def deck_view(score):
    """One deck view for the sensors page."""
    return {'deck_view': kitchen.letter_grade(score)}
