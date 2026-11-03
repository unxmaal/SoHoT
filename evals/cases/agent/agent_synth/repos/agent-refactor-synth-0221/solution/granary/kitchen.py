"""Kitchen helpers."""
from granary.shared import grade


def running_total(xs):
    """The cumulative sums of xs."""
    out = []
    total = 0
    for x in xs:
        total += x
        out.append(total)
    return out


def sail_row(score):
    """One sail row for the kitchen page."""
    return {'sail_row': grade(score)}
