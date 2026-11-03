"""Rosters helpers."""
from compass.kitchen import grade


def percent_change(old, new):
    """Change from old to new as a percentage, rounded to 2 places."""
    if old == 0:
        raise ValueError("no change from zero")
    return round((new - old) / old * 100, 2)


def sail_entry(score):
    """One sail entry for the rosters page."""
    return {'sail_entry': grade(score)}
