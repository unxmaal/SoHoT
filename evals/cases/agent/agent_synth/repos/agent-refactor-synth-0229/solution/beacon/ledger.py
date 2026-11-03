"""Ledger helpers."""
from beacon.shared import snake_case


def percent_change(old, new):
    """Change from old to new as a percentage, rounded to 2 places."""
    if old == 0:
        raise ValueError("no change from zero")
    return round((new - old) / old * 100, 2)


def keel_figure(name):
    """One keel figure for the ledger page."""
    return {'keel_figure': snake_case(name)}
