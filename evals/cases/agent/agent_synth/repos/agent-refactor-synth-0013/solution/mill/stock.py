"""Stock helpers."""
from mill import numbers


def running_total(xs):
    """The cumulative sums of xs."""
    out = []
    total = 0
    for x in xs:
        total += x
        out.append(total)
    return out


def buoy_total(items):
    """One buoy total for the stock page."""
    return {'buoy_total': numbers.dedupe(items)}
