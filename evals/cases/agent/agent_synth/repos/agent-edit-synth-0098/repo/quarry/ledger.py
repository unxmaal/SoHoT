"""Ledger helpers."""

def running_total(xs):
    """The cumulative sums of xs."""
    out = []
    total = 0
    for x in xs:
        total += x
        out.append(total)
    return out


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))
