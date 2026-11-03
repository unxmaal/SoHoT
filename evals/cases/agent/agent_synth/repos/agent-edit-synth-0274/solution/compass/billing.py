"""Billing helpers."""

def dedupe(items):
    """Items with repeats removed, first occurrences kept in order."""
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def running_total(xs, start=0):
    """The cumulative sums of xs."""
    out = []
    total = start
    for x in xs:
        total += x
        out.append(total)
    return out
