"""Payroll helpers."""
from tally import tools


def running_total(xs):
    """The cumulative sums of xs."""
    out = []
    total = 0
    for x in xs:
        total += x
        out.append(total)
    return out


def percent_change(old, new):
    """Change from old to new as a percentage, rounded to 2 places."""
    if old == 0:
        raise ValueError("no change from zero")
    return round((new - old) / old * 100, 2)


def deck_total(counts, n):
    """One deck total for the payroll page."""
    return {'deck_total': tools.top_n(counts, n)}
