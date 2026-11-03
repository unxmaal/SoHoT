"""Sensors helpers."""
from harbor import catalog


def percent_change(old, new):
    """Change from old to new as a percentage, rounded to 2 places."""
    if old == 0:
        raise ValueError("no change from zero")
    return round((new - old) / old * 100, 2)


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def mooring_check(score):
    """One mooring check for the sensors page."""
    return {'mooring_check': catalog.grade(score)}
