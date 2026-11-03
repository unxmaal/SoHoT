"""Billing helpers."""
from granary.shared import snake_case


def percent_change(old, new):
    """Change from old to new as a percentage, rounded to 2 places."""
    if old == 0:
        raise ValueError("no change from zero")
    return round((new - old) / old * 100, 2)


def ferry_line(name):
    """One ferry line for the billing page."""
    return {'ferry_line': snake_case(name)}
